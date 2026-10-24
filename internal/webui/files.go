package webui

import (
	"bytes"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type FileEntry struct {
	Name      string `json:"name"`
	Path      string `json:"path"`
	Directory bool   `json:"directory"`
	Symlink   bool   `json:"symlink"`
	Size      int64  `json:"size"`
	Modified  string `json:"modified"`
	Mode      string `json:"mode"`
	Editable  bool   `json:"editable"`
}

func (a *App) handleFilesList(w http.ResponseWriter, r *http.Request) {
	path := r.URL.Query().Get("path")
	if a.cfg.DemoMode {
		if path == "" {
			path = "/ffp"
		}
		clean := filepath.Clean(path)
		if clean != "/ffp" && !strings.HasPrefix(clean, "/ffp"+string(os.PathSeparator)) {
			writeError(w, http.StatusBadRequest, "Demo režim povoluje pouze ukázkovou cestu /ffp.")
			return
		}
		entries := []FileEntry{}
		if clean == "/ffp" {
			for _, name := range []string{"bin", "etc", "start"} {
				entries = append(entries, FileEntry{Name: name, Path: filepath.Join("/ffp", name), Directory: true, Mode: "drwxr-xr-x"})
			}
		}
		parent := ""
		if clean != "/ffp" {
			parent = filepath.Dir(clean)
		}
		writeJSON(w, http.StatusOK, map[string]any{"path": clean, "parent": parent, "entries": entries, "demo": true})
		return
	}
	if path == "" {
		path = a.cfg.AllowedRoots[0]
	}
	resolved, _, err := a.securePath(path, false)
	if err != nil {
		writeError(w, http.StatusBadRequest, "Cesta není v povoleném kořeni nebo obsahuje symlink.")
		return
	}
	info, err := os.Stat(resolved)
	if err != nil || !info.IsDir() {
		writeError(w, http.StatusNotFound, "Adresář nebyl nalezen.")
		return
	}
	items, err := os.ReadDir(resolved)
	if err != nil {
		writeError(w, http.StatusForbidden, "Adresář nelze přečíst.")
		return
	}
	out := make([]FileEntry, 0, len(items))
	for _, item := range items {
		if a.isStatePath(filepath.Join(resolved, item.Name())) {
			continue
		}
		if isSensitivePath(filepath.Join(resolved, item.Name())) {
			continue
		}
		fi, err := item.Info()
		if err != nil {
			continue
		}
		symlink := item.Type()&os.ModeSymlink != 0
		isDir := !symlink && fi.IsDir()
		p := filepath.Join(resolved, item.Name())
		out = append(out, FileEntry{Name: item.Name(), Path: p, Directory: isDir, Symlink: symlink, Size: fi.Size(), Modified: fi.ModTime().Format(time.RFC3339), Mode: fi.Mode().String(), Editable: !symlink && fi.Mode().IsRegular() && textExtension(item.Name())})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Directory != out[j].Directory {
			return out[i].Directory
		}
		return strings.ToLower(out[i].Name) < strings.ToLower(out[j].Name)
	})
	writeJSON(w, http.StatusOK, map[string]any{"path": resolved, "parent": safeParent(resolved, a.cfg.AllowedRoots), "entries": out})
}

func safeParent(path string, roots []string) string {
	for _, root := range roots {
		if filepath.Clean(path) == filepath.Clean(root) {
			return ""
		}
		if resolved, err := filepath.EvalSymlinks(root); err == nil && filepath.Clean(path) == filepath.Clean(resolved) {
			return ""
		}
	}
	return filepath.Dir(path)
}

func (a *App) securePath(raw string, allowMissingFinal bool) (string, string, error) {
	if raw == "" || strings.ContainsRune(raw, '\x00') {
		return "", "", fmt.Errorf("empty or NUL path")
	}
	if !filepath.IsAbs(raw) {
		return "", "", fmt.Errorf("absolute path required")
	}
	clean := filepath.Clean(raw)
	if isSensitivePath(clean) {
		return "", "", fmt.Errorf("sensitive path is not exposed")
	}
	for _, root := range a.cfg.AllowedRoots {
		root = filepath.Clean(root)
		rootResolved, err := filepath.EvalSymlinks(root)
		if err != nil {
			return "", "", err
		}
		if a.isStatePath(clean) {
			return "", "", fmt.Errorf("state directory is not exposed")
		}
		base := ""
		if clean == root || strings.HasPrefix(clean, root+string(os.PathSeparator)) {
			base = root
		} else if clean == rootResolved || strings.HasPrefix(clean, rootResolved+string(os.PathSeparator)) {
			base = rootResolved
		}
		if base == "" {
			continue
		}
		rel, err := filepath.Rel(base, clean)
		if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
			continue
		}
		cur := rootResolved
		if rel == "." {
			return rootResolved, rootResolved, nil
		}
		parts := strings.Split(rel, string(os.PathSeparator))
		for i, part := range parts {
			if part == "" || part == "." || part == ".." {
				return "", "", fmt.Errorf("invalid component")
			}
			cur = filepath.Join(cur, part)
			fi, err := os.Lstat(cur)
			if err != nil {
				if os.IsNotExist(err) && allowMissingFinal && i == len(parts)-1 {
					return cur, rootResolved, nil
				}
				return "", "", err
			}
			if fi.Mode()&os.ModeSymlink != 0 {
				return "", "", fmt.Errorf("symlink not allowed")
			}
			if i < len(parts)-1 && !fi.IsDir() {
				return "", "", fmt.Errorf("not a directory")
			}
		}
		resolved, err := filepath.EvalSymlinks(cur)
		if err != nil {
			return "", "", err
		}
		if resolved != rootResolved && !strings.HasPrefix(resolved, rootResolved+string(os.PathSeparator)) {
			return "", "", fmt.Errorf("outside root")
		}
		return resolved, rootResolved, nil
	}
	return "", "", fmt.Errorf("outside allowed roots")
}

func (a *App) isStatePath(path string) bool {
	state := filepath.Clean(a.cfg.StateDir)
	p := filepath.Clean(path)
	if p == state || strings.HasPrefix(p, state+string(os.PathSeparator)) {
		return true
	}
	if resolved, err := filepath.EvalSymlinks(state); err == nil {
		return p == resolved || strings.HasPrefix(p, resolved+string(os.PathSeparator))
	}
	return false
}

func isSensitivePath(path string) bool {
	p := strings.ToLower(filepath.Clean(path))
	base := strings.ToLower(filepath.Base(p))
	if strings.HasSuffix(p, "/ffp/etc/ffp-webui/environment") || p == strings.ToLower(envFilePath) || strings.Contains(p, string(os.PathSeparator)+".ssh"+string(os.PathSeparator)) {
		return true
	}
	if base == ".env" || strings.HasPrefix(base, "id_rsa") || strings.HasPrefix(base, "id_ed25519") || strings.HasPrefix(base, "id_ecdsa") || base == "identity" {
		return true
	}
	if strings.HasPrefix(base, "ssh_host_") && strings.HasSuffix(base, "_key") {
		return true
	}
	switch filepath.Ext(base) {
	case ".pem", ".key", ".p12", ".pfx", ".ppk", ".secret":
		return true
	}
	return false
}

func textExtension(name string) bool {
	ext := strings.ToLower(filepath.Ext(name))
	switch ext {
	case ".txt", ".conf", ".cfg", ".ini", ".json", ".yaml", ".yml", ".toml", ".md", ".sh", ".profile", ".log", ".list", ".xml", ".html", ".css", ".js", ".service", ".cron", ".tab":
		return true
	default:
		return false
	}
}

func (a *App) handleFileRead(w http.ResponseWriter, r *http.Request) {
	if a.cfg.DemoMode {
		writeError(w, http.StatusLocked, "Demo režim nečte soubory hostitele.")
		return
	}
	path, _, err := a.securePath(r.URL.Query().Get("path"), false)
	if err != nil {
		writeError(w, http.StatusBadRequest, "Soubor je mimo povolený kořen nebo obsahuje symlink.")
		return
	}
	fi, err := os.Stat(path)
	if err != nil || !fi.Mode().IsRegular() || fi.Size() > 1<<20 {
		writeError(w, http.StatusBadRequest, "Lze číst pouze běžné textové soubory do 1 MiB.")
		return
	}
	if !textExtension(path) {
		writeError(w, http.StatusUnsupportedMediaType, "Tento typ souboru není povolen v textovém editoru.")
		return
	}
	b, err := os.ReadFile(path)
	if err != nil {
		writeError(w, http.StatusForbidden, "Soubor nelze přečíst.")
		return
	}
	if bytes.IndexByte(b, 0) >= 0 {
		writeError(w, http.StatusUnsupportedMediaType, "Soubor obsahuje binární data.")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"path": path, "content": string(b), "size": len(b)})
}

func (a *App) handleFileSave(w http.ResponseWriter, r *http.Request) {
	if !a.requireLive(w) {
		return
	}
	var req struct {
		Path    string `json:"path"`
		Content string `json:"content"`
		Confirm string `json:"confirm"`
	}
	if err := decodeJSON(w, r, &req, (1<<20)+4096); err != nil {
		writeError(w, http.StatusBadRequest, "Neplatný nebo příliš velký požadavek.")
		return
	}
	path, _, err := a.securePath(req.Path, false)
	if err != nil {
		writeError(w, http.StatusBadRequest, "Cesta není povolena.")
		return
	}
	fi, err := os.Stat(path)
	if err != nil || !fi.Mode().IsRegular() || !textExtension(path) {
		writeError(w, http.StatusUnsupportedMediaType, "Upravovat lze pouze existující povolené textové soubory.")
		return
	}
	if len(req.Content) > 1<<20 || strings.ContainsRune(req.Content, '\x00') {
		writeError(w, http.StatusRequestEntityTooLarge, "Text je příliš velký nebo obsahuje NUL.")
		return
	}
	if req.Confirm != "SAVE "+filepath.Base(path) {
		writeError(w, http.StatusBadRequest, "Před uložením potvrďte přesný název souboru.")
		return
	}
	if _, err := a.backupFile(path, "file"); err != nil {
		writeError(w, http.StatusBadGateway, "Záloha původního souboru selhala; soubor nebyl změněn.")
		return
	}
	if err := atomicWrite(path, []byte(req.Content), fi.Mode().Perm()); err != nil {
		writeError(w, http.StatusBadGateway, "Soubor nelze atomicky uložit.")
		return
	}
	a.audit(r, "file_save", path, "ok")
	writeJSON(w, http.StatusOK, map[string]string{"ok": "true", "backup": "vytvořena"})
}

func (a *App) handleFileUpload(w http.ResponseWriter, r *http.Request) {
	if !a.requireLive(w) {
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, a.cfg.MaxUploadBytes+(1<<20))
	if err := r.ParseMultipartForm(a.cfg.MaxUploadBytes); err != nil {
		writeError(w, http.StatusRequestEntityTooLarge, "Upload je příliš velký nebo neplatný.")
		return
	}
	dir, _, err := a.securePath(r.FormValue("path"), false)
	if err != nil {
		writeError(w, http.StatusBadRequest, "Cílová složka není povolena.")
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil {
		writeError(w, http.StatusBadRequest, "Chybí soubor.")
		return
	}
	defer file.Close()
	name := filepath.Base(header.Filename)
	if !allowedName(name) || strings.Contains(name, "..") {
		writeError(w, http.StatusBadRequest, "Název souboru není bezpečný.")
		return
	}
	target, _, err := a.securePath(filepath.Join(dir, name), true)
	if err != nil {
		writeError(w, http.StatusBadRequest, "Cílová cesta není povolena.")
		return
	}
	if _, err := os.Lstat(target); err == nil {
		writeError(w, http.StatusConflict, "Soubor již existuje; přepsání přes upload není povoleno.")
		return
	}
	if strings.HasSuffix(strings.ToLower(name), ".txz") || strings.HasSuffix(strings.ToLower(name), ".tgz") {
		writeError(w, http.StatusBadRequest, "Balíčky nahrajte na kartě Balíčky do oddělené staging složky.")
		return
	}
	if err := copyLimitedFile(target, file, a.cfg.MaxUploadBytes, 0600); err != nil {
		writeError(w, http.StatusBadGateway, "Upload se nepodařilo uložit.")
		return
	}
	a.audit(r, "file_upload", target, "ok")
	writeJSON(w, http.StatusCreated, map[string]string{"path": target, "ok": "true"})
}

func copyLimitedFile(path string, src io.Reader, limit int64, mode os.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return err
	}
	tmp := path + ".upload-" + randomID()
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_EXCL|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	written, err := io.Copy(f, io.LimitReader(src, limit+1))
	if err == nil && written > limit {
		err = fmt.Errorf("upload too large")
	}
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		_ = os.Remove(tmp)
		return err
	}
	if err := os.Link(tmp, path); err != nil {
		_ = os.Remove(tmp)
		return err
	}
	_ = os.Remove(tmp)
	return nil
}

func (a *App) handleFileDownload(w http.ResponseWriter, r *http.Request) {
	if a.cfg.DemoMode {
		writeError(w, http.StatusLocked, "Demo režim nestahuje soubory hostitele.")
		return
	}
	path, _, err := a.securePath(r.URL.Query().Get("path"), false)
	if err != nil {
		writeError(w, http.StatusBadRequest, "Cesta není povolena.")
		return
	}
	fi, err := os.Stat(path)
	if err != nil || !fi.Mode().IsRegular() || fi.Size() > 256<<20 {
		writeError(w, http.StatusBadRequest, "Soubor nelze stáhnout nebo překračuje limit.")
		return
	}
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=%q", filepath.Base(path)))
	http.ServeFile(w, r, path)
}

func (a *App) handleFileDelete(w http.ResponseWriter, r *http.Request) {
	if !a.requireLive(w) {
		return
	}
	var req struct {
		Path    string `json:"path"`
		Confirm string `json:"confirm"`
	}
	if err := decodeJSON(w, r, &req, 4096); err != nil {
		writeError(w, http.StatusBadRequest, "Neplatný JSON požadavek.")
		return
	}
	path, _, err := a.securePath(req.Path, false)
	if err != nil {
		writeError(w, http.StatusBadRequest, "Cesta není povolena.")
		return
	}
	if req.Confirm != "DELETE "+filepath.Base(path) {
		writeError(w, http.StatusBadRequest, "Pro smazání napište DELETE a přesný název souboru.")
		return
	}
	fi, err := os.Lstat(path)
	if err != nil || !fi.Mode().IsRegular() || fi.Mode()&os.ModeSymlink != 0 {
		writeError(w, http.StatusBadRequest, "Mazat lze pouze běžný soubor, nikoli adresář nebo symlink.")
		return
	}
	if _, err := a.backupFile(path, "deleted"); err != nil {
		writeError(w, http.StatusBadGateway, "Záloha selhala; soubor nebyl smazán.")
		return
	}
	if err := os.Remove(path); err != nil {
		writeError(w, http.StatusBadGateway, "Soubor se nepodařilo smazat.")
		return
	}
	a.audit(r, "file_delete", path, "ok")
	writeJSON(w, http.StatusOK, map[string]string{"ok": "true", "backup": "vytvořena"})
}

func atomicWrite(path string, b []byte, mode os.FileMode) error {
	tmp := path + ".save-" + randomID()
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_EXCL|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	if _, err = f.Write(b); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		_ = os.Remove(tmp)
		return err
	}
	return os.Rename(tmp, path)
}

func (a *App) backupFileIfExists(path, label string) error {
	if _, err := os.Lstat(path); os.IsNotExist(err) {
		return nil
	} else if err != nil {
		return err
	}
	_, err := a.backupFile(path, label)
	return err
}

func (a *App) backupFile(path, label string) (string, error) {
	fi, err := os.Lstat(path)
	if err != nil {
		return "", err
	}
	if !fi.Mode().IsRegular() || fi.Mode()&os.ModeSymlink != 0 {
		return "", fmt.Errorf("backup source must be regular file")
	}
	if fi.Size() < 0 || fi.Size() > a.cfg.MaxPackageBytes {
		return "", fmt.Errorf("backup source exceeds configured limit")
	}
	in, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer in.Close()
	name := filepath.Base(path)
	stamp := time.Now().UTC().Format("20060102T150405Z")
	backupName := fmt.Sprintf("%s-%s-%s-%s", label, stamp, randomID(), name)
	backupPath := filepath.Join(a.statePath("backups"), backupName)
	if err := os.MkdirAll(filepath.Dir(backupPath), 0700); err != nil {
		return "", err
	}
	if err := copyLimitedFile(backupPath, in, a.cfg.MaxPackageBytes, 0600); err != nil {
		return "", err
	}
	return backupPath, nil
}
