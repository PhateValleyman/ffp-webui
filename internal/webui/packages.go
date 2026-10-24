package webui

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

var shaPattern = regexp.MustCompile(`^[A-Fa-f0-9]{64}$`)

type PackageArchive struct {
	Name   string `json:"name"`
	Path   string `json:"path"`
	Size   int64  `json:"size"`
	SHA256 string `json:"sha256"`
	Source string `json:"source"`
}

func (a *App) handlePackagesGet(w http.ResponseWriter, r *http.Request) {
	if a.cfg.DemoMode {
		writeJSON(w, http.StatusOK, map[string]any{"manager": "funpkg (údaj neověřen)", "inventory_source": "/ffp/var/packages (neověřeno)", "installed": []string{"funpkg-0.6.3 (pouze známý repozitář; instalace neověřena)"}, "archives": []PackageArchive{}, "note": "Před instalací ověřte architekturu, původ, podpis/hash a kompatibilitu."})
		return
	}
	installed := []string{}
	if entries, err := os.ReadDir("/ffp/var/packages"); err == nil {
		for _, e := range entries {
			if allowedName(e.Name()) {
				installed = append(installed, e.Name())
			}
		}
	}
	sort.Strings(installed)
	archives := []PackageArchive{}
	roots := append([]string{}, a.cfg.PackageRoots...)
	roots = append(roots, a.statePath("packages"))
	for _, root := range roots {
		entries, err := os.ReadDir(root)
		if err != nil {
			continue
		}
		for _, e := range entries {
			if e.Type()&os.ModeSymlink != 0 || e.IsDir() || !isPackageName(e.Name()) {
				continue
			}
			path := filepath.Join(root, e.Name())
			fi, err := e.Info()
			if err != nil || !fi.Mode().IsRegular() {
				continue
			}
			hash, err := fileSHA(path)
			if err != nil {
				continue
			}
			source := "uložiště NAS"
			if strings.HasPrefix(path, a.statePath("packages")+string(os.PathSeparator)) {
				source = "staging WebUI"
			}
			archives = append(archives, PackageArchive{Name: e.Name(), Path: path, Size: fi.Size(), SHA256: hash, Source: source})
		}
	}
	sort.Slice(archives, func(i, j int) bool { return archives[i].Name < archives[j].Name })
	funpkg, err := exec.LookPath("funpkg")
	if err != nil {
		funpkg = "nedostupný"
	}
	writeJSON(w, http.StatusOK, map[string]any{"manager": funpkg, "inventory_source": "/ffp/var/packages (neověřeno; potvrďte na zařízení)", "installed": installed, "archives": archives, "note": "Seznam archivů není důkazem instalace. Kontrolní součet potvrzuje jen shodu s uživatelem zadanou hodnotou, nikoli důvěryhodnost balíčku."})
}

func isPackageName(name string) bool {
	lower := strings.ToLower(name)
	return allowedName(name) && (strings.HasSuffix(lower, ".txz") || strings.HasSuffix(lower, ".tgz"))
}

func (a *App) handlePackageUpload(w http.ResponseWriter, r *http.Request) {
	if !a.requireLive(w) {
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, a.cfg.MaxPackageBytes+(1<<20))
	if err := r.ParseMultipartForm(a.cfg.MaxPackageBytes); err != nil {
		writeError(w, http.StatusRequestEntityTooLarge, "Balíček je příliš velký nebo upload neplatný.")
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil {
		writeError(w, http.StatusBadRequest, "Chybí soubor balíčku.")
		return
	}
	defer file.Close()
	name := filepath.Base(header.Filename)
	if !isPackageName(name) {
		writeError(w, http.StatusBadRequest, "Povolené formáty jsou pouze .txz a .tgz.")
		return
	}
	if err := os.MkdirAll(a.statePath("packages"), 0700); err != nil {
		writeError(w, http.StatusInternalServerError, "Nelze vytvořit staging.")
		return
	}
	dest := filepath.Join(a.statePath("packages"), name)
	if _, err := os.Lstat(dest); err == nil {
		writeError(w, http.StatusConflict, "Balíček tohoto názvu již existuje ve stagingu.")
		return
	}
	if err := copyLimitedFile(dest, file, a.cfg.MaxPackageBytes, 0600); err != nil {
		writeError(w, http.StatusBadGateway, "Upload balíčku selhal.")
		return
	}
	hash, err := fileSHA(dest)
	if err != nil {
		_ = os.Remove(dest)
		writeError(w, http.StatusInternalServerError, "Nelze vypočítat SHA-256.")
		return
	}
	a.audit(r, "package_upload", name, "staged")
	writeJSON(w, http.StatusCreated, PackageArchive{Name: name, Path: dest, SHA256: hash, Source: "staging WebUI"})
}

func (a *App) handlePackageFetch(w http.ResponseWriter, r *http.Request) {
	if !a.requireLive(w) {
		return
	}
	var req struct {
		URL    string `json:"url"`
		SHA256 string `json:"sha256"`
	}
	if err := decodeJSON(w, r, &req, 8192); err != nil {
		writeError(w, http.StatusBadRequest, "Neplatný JSON požadavek.")
		return
	}
	if !shaPattern.MatchString(req.SHA256) {
		writeError(w, http.StatusBadRequest, "Zadejte očekávaný 64znakový SHA-256 získaný nezávisle na URL.")
		return
	}
	u, err := url.ParseRequestURI(req.URL)
	if err != nil || u.Scheme != "https" || u.Hostname() == "" || u.User != nil || u.Fragment != "" {
		writeError(w, http.StatusBadRequest, "Použijte přímou HTTPS URL bez uživatelských údajů a přesměrování.")
		return
	}
	if p := u.Port(); p != "" && p != "443" {
		writeError(w, http.StatusBadRequest, "HTTPS balíček lze stáhnout pouze ze standardního portu 443.")
		return
	}
	if !isPublicHost(u.Hostname()) {
		writeError(w, http.StatusForbidden, "Soukromé, lokální a vyhrazené síťové cíle jsou zakázány.")
		return
	}
	if err := os.MkdirAll(a.statePath("packages"), 0700); err != nil {
		writeError(w, http.StatusInternalServerError, "Nelze vytvořit staging.")
		return
	}
	name := filepath.Base(u.Path)
	if !isPackageName(name) {
		writeError(w, http.StatusBadRequest, "Cesta URL musí končit .txz nebo .tgz.")
		return
	}
	dest := filepath.Join(a.statePath("packages"), name)
	if _, err := os.Lstat(dest); err == nil {
		writeError(w, http.StatusConflict, "Balíček tohoto názvu již existuje ve stagingu.")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Minute)
	defer cancel()
	if err := downloadPackage(ctx, u, dest, a.cfg.MaxPackageBytes); err != nil {
		_ = os.Remove(dest)
		a.audit(r, "package_download", name, "failed")
		writeError(w, http.StatusBadGateway, "Stažení balíčku selhalo: "+err.Error())
		return
	}
	actual, err := fileSHA(dest)
	if err != nil || !strings.EqualFold(actual, req.SHA256) {
		_ = os.Remove(dest)
		a.audit(r, "package_download", name, "hash-mismatch")
		writeError(w, http.StatusUnprocessableEntity, "SHA-256 balíčku nesouhlasí; soubor byl odstraněn.")
		return
	}
	a.audit(r, "package_download", name, "verified")
	writeJSON(w, http.StatusCreated, PackageArchive{Name: name, Path: dest, SHA256: actual, Source: "HTTPS staging"})
}

func isPublicHost(host string) bool {
	if ip := net.ParseIP(host); ip != nil {
		return publicIP(ip)
	}
	ips, err := net.LookupIP(host)
	if err != nil || len(ips) == 0 {
		return false
	}
	for _, ip := range ips {
		if !publicIP(ip) {
			return false
		}
	}
	return true
}

func publicIP(ip net.IP) bool {
	return ip != nil && !ip.IsLoopback() && !ip.IsPrivate() && !ip.IsLinkLocalUnicast() && !ip.IsLinkLocalMulticast() && !ip.IsUnspecified() && !ip.IsMulticast()
}

func downloadPackage(ctx context.Context, u *url.URL, dest string, max int64) error {
	dialer := &net.Dialer{Timeout: 15 * time.Second, KeepAlive: 30 * time.Second}
	transport := &http.Transport{DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
		host, port, err := net.SplitHostPort(address)
		if err != nil {
			return nil, err
		}
		ips, err := net.LookupIP(host)
		if err != nil {
			return nil, err
		}
		for _, ip := range ips {
			if !publicIP(ip) {
				continue
			}
			conn, err := dialer.DialContext(ctx, network, net.JoinHostPort(ip.String(), port))
			if err == nil {
				return conn, nil
			}
		}
		return nil, fmt.Errorf("host nevede na veřejnou IP")
	}}
	client := &http.Client{Transport: transport, Timeout: 10 * time.Minute, CheckRedirect: func(req *http.Request, via []*http.Request) error { return http.ErrUseLastResponse }}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", "FFP-WebUI-package-fetch/0.1")
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("HTTP status %s (redirects are blocked)", resp.Status)
	}
	if resp.ContentLength > max {
		return fmt.Errorf("soubor překračuje limit velikosti")
	}
	return copyLimitedFile(dest, resp.Body, max, 0600)
}

func (a *App) packagePath(raw string) (string, error) {
	if raw == "" || !filepath.IsAbs(raw) {
		return "", fmt.Errorf("absolute package path required")
	}
	clean := filepath.Clean(raw)
	roots := append([]string{}, a.cfg.PackageRoots...)
	roots = append(roots, a.statePath("packages"))
	for _, root := range roots {
		root = filepath.Clean(root)
		if clean != root && !strings.HasPrefix(clean, root+string(os.PathSeparator)) {
			continue
		}
		if filepath.Ext(strings.ToLower(clean)) != ".txz" && filepath.Ext(strings.ToLower(clean)) != ".tgz" {
			return "", fmt.Errorf("unsupported package extension")
		}
		fi, err := os.Lstat(clean)
		if err != nil {
			return "", err
		}
		if !fi.Mode().IsRegular() || fi.Mode()&os.ModeSymlink != 0 || fi.Size() <= 0 || fi.Size() > a.cfg.MaxPackageBytes {
			return "", fmt.Errorf("package must be a regular non-symlink file")
		}
		resolved, err := filepath.EvalSymlinks(clean)
		if err != nil {
			return "", err
		}
		rootResolved, err := filepath.EvalSymlinks(root)
		if err != nil {
			return "", err
		}
		if resolved != rootResolved && !strings.HasPrefix(resolved, rootResolved+string(os.PathSeparator)) {
			return "", fmt.Errorf("package outside configured root")
		}
		return resolved, nil
	}
	return "", fmt.Errorf("package path outside configured package roots")
}

func (a *App) handlePackageAction(w http.ResponseWriter, r *http.Request) {
	if !a.requireLive(w) {
		return
	}
	var req struct {
		Action  string `json:"action"`
		Path    string `json:"path"`
		SHA256  string `json:"sha256"`
		Confirm string `json:"confirm"`
	}
	if err := decodeJSON(w, r, &req, 8192); err != nil {
		writeError(w, http.StatusBadRequest, "Neplatný JSON požadavek.")
		return
	}
	path, err := a.packagePath(req.Path)
	if err != nil {
		writeError(w, http.StatusBadRequest, "Balíček není v povoleném úložišti.")
		return
	}
	if !shaPattern.MatchString(req.SHA256) {
		writeError(w, http.StatusBadRequest, "Zadejte kontrolní součet SHA-256.")
		return
	}
	actual, err := fileSHA(path)
	if err != nil || !strings.EqualFold(actual, req.SHA256) {
		writeError(w, http.StatusUnprocessableEntity, "SHA-256 nesouhlasí; příkaz funpkg nebyl spuštěn.")
		return
	}
	if req.Confirm != strings.ToUpper(req.Action)+" "+filepath.Base(path) {
		writeError(w, http.StatusBadRequest, "Potvrďte přesnou akci a název archivu.")
		return
	}
	flag := ""
	switch req.Action {
	case "install":
		flag = "-i"
	case "reinstall":
		flag = "-u"
	case "remove":
		flag = "-r"
	case "backup":
		name := "package-" + time.Now().UTC().Format("20060102T150405Z") + "-" + randomID() + "-" + filepath.Base(path)
		dst := filepath.Join(a.statePath("backups", "packages"), name)
		if err := os.MkdirAll(filepath.Dir(dst), 0700); err != nil {
			writeError(w, http.StatusInternalServerError, "Nelze vytvořit zálohu.")
			return
		}
		in, err := os.Open(path)
		if err != nil {
			writeError(w, http.StatusBadGateway, "Archiv nelze přečíst.")
			return
		}
		defer in.Close()
		if err := copyLimitedFile(dst, in, a.cfg.MaxPackageBytes, 0600); err != nil {
			writeError(w, http.StatusBadGateway, "Záloha balíčku selhala.")
			return
		}
		a.audit(r, "package_backup", filepath.Base(path), "ok")
		writeJSON(w, http.StatusOK, map[string]string{"backup": dst, "sha256": actual})
		return
	default:
		writeError(w, http.StatusBadRequest, "Povolené akce: install, reinstall, remove, backup.")
		return
	}
	if _, err := exec.LookPath("funpkg"); err != nil {
		writeError(w, http.StatusServiceUnavailable, "Příkaz funpkg není v PATH WebUI.")
		return
	}
	job, err := a.jobs.start("funpkg "+flag+" "+filepath.Base(path), func() (string, error) {
		ctx, cancel := context.WithTimeout(context.Background(), a.operationTimeout())
		defer cancel()
		cmd := exec.CommandContext(ctx, "funpkg", flag, path)
		cmd.Env = []string{"PATH=/ffp/bin:/ffp/sbin:/bin:/sbin", "HOME=/ffp/home/root", "LANG=C", "TERM=dumb"}
		out, err := cmd.CombinedOutput()
		return limitedText(out), err
	})
	if err != nil {
		writeError(w, http.StatusConflict, err.Error())
		return
	}
	a.audit(r, "package_"+req.Action, filepath.Base(path), "started")
	writeJSON(w, http.StatusAccepted, job)
}

func (a *App) handleJobGet(w http.ResponseWriter, r *http.Request) {
	id := strings.TrimPrefix(r.URL.Path, "/api/jobs/")
	if id == "" || strings.Contains(id, "/") {
		writeError(w, http.StatusBadRequest, "Neplatné ID úlohy.")
		return
	}
	job, ok := a.jobs.get(id)
	if !ok {
		writeError(w, http.StatusNotFound, "Úloha nebyla nalezena.")
		return
	}
	writeJSON(w, http.StatusOK, job)
}

func fileSHA(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}
