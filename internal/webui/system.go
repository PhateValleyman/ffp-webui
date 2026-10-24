package webui

import (
	"bufio"
	"context"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

const ffpStartDir = "/ffp/start"
const envFilePath = "/ffp/etc/ffp-webui/environment"

var envKeyPattern = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]{0,63}$`)

func allowedManagedEnvKey(key string) bool {
	return envKeyPattern.MatchString(key) && (strings.HasPrefix(key, "FFP_") || key == "LANG" || key == "LC_ALL" || key == "TZ")
}

type SystemInfo struct {
	Hostname string            `json:"hostname"`
	Kernel   string            `json:"kernel"`
	Arch     string            `json:"arch"`
	Uptime   string            `json:"uptime"`
	Memory   map[string]string `json:"memory"`
	Storage  []StorageInfo     `json:"storage"`
	IPs      []string          `json:"ips"`
	Demo     bool              `json:"demo"`
}

type StorageInfo struct {
	Path  string `json:"path"`
	Total string `json:"total"`
	Used  string `json:"used"`
	Free  string `json:"free"`
}

type Service struct {
	Name    string `json:"name"`
	Enabled bool   `json:"enabled"`
	Status  string `json:"status"`
	Script  string `json:"script"`
}

func (a *App) handleSystem(w http.ResponseWriter, r *http.Request) {
	if a.cfg.DemoMode {
		writeJSON(w, http.StatusOK, SystemInfo{Hostname: "NSA320 (ukázkový režim)", Kernel: "údaj není ověřen", Arch: "ARMv5TE / soft-float (zadaný profil)", Uptime: "demo", Memory: map[string]string{"total": "512 MiB (historický údaj)", "free": "—"}, Storage: []StorageInfo{{Path: "/ffp", Total: "—", Used: "—", Free: "—"}}, IPs: []string{"192.168.1.20 (požadovaná adresa; neověřeno)"}, Demo: true})
		return
	}
	info := SystemInfo{Memory: map[string]string{}, Demo: false}
	if h, err := os.Hostname(); err == nil {
		info.Hostname = h
	}
	if b, err := os.ReadFile("/proc/version"); err == nil {
		info.Kernel = strings.TrimSpace(string(b))
	}
	if b, err := os.ReadFile("/proc/cpuinfo"); err == nil {
		for _, line := range strings.Split(string(b), "\n") {
			if strings.HasPrefix(strings.ToLower(line), "model name") || strings.HasPrefix(strings.ToLower(line), "processor") || strings.HasPrefix(strings.ToLower(line), "cpu architecture") {
				info.Arch = strings.TrimSpace(strings.SplitN(line, ":", 2)[1])
				break
			}
		}
	}
	if b, err := os.ReadFile("/proc/uptime"); err == nil {
		fields := strings.Fields(string(b))
		if len(fields) > 0 {
			if seconds, e := strconv.ParseFloat(fields[0], 64); e == nil {
				info.Uptime = (time.Duration(seconds * float64(time.Second))).Round(time.Second).String()
			}
		}
	}
	if b, err := os.ReadFile("/proc/meminfo"); err == nil {
		for _, line := range strings.Split(string(b), "\n") {
			if strings.HasPrefix(line, "MemTotal:") || strings.HasPrefix(line, "MemAvailable:") || strings.HasPrefix(line, "MemFree:") {
				parts := strings.Fields(line)
				if len(parts) >= 2 {
					info.Memory[strings.TrimSuffix(parts[0], ":")] = parts[1] + " " + parts[2]
				}
			}
		}
	}
	if ips, err := net.InterfaceAddrs(); err == nil {
		for _, addr := range ips {
			var ip net.IP
			switch v := addr.(type) {
			case *net.IPNet:
				ip = v.IP
			case *net.IPAddr:
				ip = v.IP
			}
			if ip != nil && !ip.IsLoopback() {
				info.IPs = append(info.IPs, ip.String())
			}
		}
	}
	for _, p := range []string{"/", "/ffp"} {
		if _, err := os.Stat(p); err != nil {
			continue
		}
		ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
		out, err := exec.CommandContext(ctx, "df", "-k", p).Output()
		cancel()
		if err != nil {
			continue
		}
		lines := strings.Split(strings.TrimSpace(string(out)), "\n")
		if len(lines) < 2 {
			continue
		}
		fields := strings.Fields(lines[len(lines)-1])
		if len(fields) >= 5 {
			info.Storage = append(info.Storage, StorageInfo{Path: p, Total: fields[1], Used: fields[2], Free: fields[3]})
		}
	}
	writeJSON(w, http.StatusOK, info)
}

func (a *App) handleServices(w http.ResponseWriter, r *http.Request) {
	if a.cfg.DemoMode {
		writeJSON(w, http.StatusOK, []Service{{Name: "sshd.sh", Enabled: true, Status: "unknown (demo)", Script: "/ffp/start/sshd.sh"}, {Name: "lighttpd.sh", Enabled: false, Status: "unknown (demo)", Script: "/ffp/start/lighttpd.sh"}})
		return
	}
	entries, err := os.ReadDir(ffpStartDir)
	if err != nil {
		writeJSON(w, http.StatusOK, []Service{})
		return
	}
	ps := processSnapshot(r.Context())
	out := make([]Service, 0, len(entries))
	for _, e := range entries {
		name := e.Name()
		if !strings.HasSuffix(name, ".sh") || name == "ffp-webui.sh" || e.Type()&os.ModeSymlink != 0 || !e.Type().IsRegular() {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		enabled := info.Mode().Perm()&0111 != 0
		base := strings.TrimSuffix(name, ".sh")
		status := "unknown"
		if processMatches(ps, base) {
			status = "running"
		} else if enabled {
			status = "not detected"
		} else {
			status = "disabled"
		}
		out = append(out, Service{Name: name, Enabled: enabled, Status: status, Script: filepath.Join(ffpStartDir, name)})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	writeJSON(w, http.StatusOK, out)
}

func processSnapshot(ctx context.Context) string {
	c, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	out, err := exec.CommandContext(c, "ps").Output()
	if err != nil {
		return ""
	}
	return strings.ToLower(string(out))
}

func processMatches(snapshot, name string) bool {
	if snapshot == "" || name == "" {
		return false
	}
	for _, line := range strings.Split(snapshot, "\n") {
		lower := strings.ToLower(line)
		if strings.Contains(lower, "/"+name) || strings.Contains(lower, " "+name+" ") || strings.HasSuffix(strings.TrimSpace(lower), " "+name) {
			return true
		}
	}
	return false
}

func (a *App) handleServiceAction(w http.ResponseWriter, r *http.Request) {
	if !a.requireLive(w) {
		return
	}
	var req struct {
		Name    string `json:"name"`
		Action  string `json:"action"`
		Confirm string `json:"confirm"`
	}
	if err := decodeJSON(w, r, &req, 4096); err != nil {
		writeError(w, http.StatusBadRequest, "Neplatný JSON požadavek.")
		return
	}
	if !allowedName(req.Name) || !strings.HasSuffix(req.Name, ".sh") || req.Name == "ffp-webui.sh" {
		writeError(w, http.StatusBadRequest, "Neplatný nebo chráněný start skript.")
		return
	}
	path := filepath.Join(ffpStartDir, req.Name)
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() {
		writeError(w, http.StatusNotFound, "Start skript nebyl nalezen nebo není běžný soubor.")
		return
	}
	switch req.Action {
	case "start", "stop", "kill", "restart":
		if req.Action == "kill" {
			req.Action = "stop"
		}
		if req.Confirm != strings.ToUpper(req.Action)+" "+req.Name {
			writeError(w, http.StatusBadRequest, "Chybí přesné potvrzení operace a názvu služby.")
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), a.operationTimeout())
		defer cancel()
		cmd := exec.CommandContext(ctx, "/bin/sh", path, req.Action)
		out, runErr := cmd.CombinedOutput()
		result := "ok"
		if runErr != nil {
			result = "failed"
		}
		a.audit(r, "service_"+req.Action, req.Name, result)
		if runErr != nil {
			writeJSON(w, http.StatusBadGateway, map[string]string{"error": "Skript služby skončil chybou.", "output": limitedText(out)})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"ok": "true", "output": limitedText(out)})
	case "autostart-on", "autostart-off":
		want := info.Mode().Perm()
		if req.Action == "autostart-on" {
			want |= 0111
		} else {
			want &^= 0111
		}
		if err := os.Chmod(path, want); err != nil {
			writeError(w, http.StatusBadGateway, "Nepodařilo se změnit příznak start skriptu.")
			return
		}
		a.audit(r, req.Action, req.Name, "ok")
		writeJSON(w, http.StatusOK, map[string]string{"ok": "true"})
	default:
		writeError(w, http.StatusBadRequest, "Povolené akce: start, stop/kill, restart, autostart-on/off.")
	}
}

func limitedText(b []byte) string {
	const max = 12 << 10
	if len(b) > max {
		b = b[len(b)-max:]
	}
	return strings.TrimSpace(string(b))
}

type EnvEntry struct {
	Key    string `json:"key"`
	Value  string `json:"value,omitempty"`
	Masked bool   `json:"masked"`
}

func (a *App) readEnvFile() (map[string]string, error) {
	values := map[string]string{}
	if a.cfg.DemoMode {
		return map[string]string{"FFP_ROOT": "/ffp", "FFP_MODE": "demo"}, nil
	}
	b, err := os.ReadFile(envFilePath)
	if os.IsNotExist(err) {
		return values, nil
	}
	if err != nil {
		return nil, err
	}
	s := bufio.NewScanner(strings.NewReader(string(b)))
	for s.Scan() {
		line := s.Text()
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		i := strings.IndexByte(line, '=')
		if i <= 0 {
			continue
		}
		key, value := line[:i], line[i+1:]
		if allowedManagedEnvKey(key) {
			values[key] = value
		}
	}
	return values, s.Err()
}

func (a *App) handleEnvGet(w http.ResponseWriter, r *http.Request) {
	values, err := a.readEnvFile()
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Proměnné prostředí nelze načíst.")
		return
	}
	keys := make([]string, 0, len(values))
	for k := range values {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	out := make([]EnvEntry, 0, len(keys))
	for _, key := range keys {
		entry := EnvEntry{Key: key, Masked: r.URL.Query().Get("reveal") != "1"}
		if !entry.Masked {
			entry.Value = values[key]
		}
		out = append(out, entry)
	}
	writeJSON(w, http.StatusOK, map[string]any{"scope": "FFP WebUI a jeho podprocesy; nikoli globální systémové prostředí", "entries": out})
}

func (a *App) handleEnvPost(w http.ResponseWriter, r *http.Request) {
	if !a.requireLive(w) {
		return
	}
	var req struct {
		Action  string `json:"action"`
		Key     string `json:"key"`
		Value   string `json:"value"`
		Confirm string `json:"confirm"`
	}
	if err := decodeJSON(w, r, &req, 16<<10); err != nil {
		writeError(w, http.StatusBadRequest, "Neplatný JSON požadavek.")
		return
	}
	if req.Action == "backup" {
		backup, err := a.backupFile(envFilePath, "environment")
		if err != nil {
			writeError(w, http.StatusBadGateway, "Záloha proměnných selhala.")
			return
		}
		a.audit(r, "env_backup", "environment", "ok")
		writeJSON(w, http.StatusOK, map[string]string{"backup": backup})
		return
	}
	if !allowedManagedEnvKey(req.Key) {
		writeError(w, http.StatusBadRequest, "Povoleny jsou pouze proměnné FFP_* a LANG/LC_ALL/TZ.")
		return
	}
	if strings.ContainsAny(req.Value, "\r\n\x00") || len(req.Value) > 4096 {
		writeError(w, http.StatusBadRequest, "Hodnota je příliš dlouhá nebo obsahuje nepovolený znak.")
		return
	}
	values, err := a.readEnvFile()
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Proměnné prostředí nelze načíst.")
		return
	}
	if req.Action == "delete" {
		if req.Confirm != "DELETE "+req.Key {
			writeError(w, http.StatusBadRequest, "Pro smazání napište DELETE a přesný název proměnné.")
			return
		}
		delete(values, req.Key)
	} else if req.Action == "set" {
		values[req.Key] = req.Value
	} else {
		writeError(w, http.StatusBadRequest, "Povolené akce jsou set, delete a backup.")
		return
	}
	if err := a.backupFileIfExists(envFilePath, "environment"); err != nil {
		writeError(w, http.StatusBadGateway, "Záloha původního souboru selhala; změna nebyla provedena.")
		return
	}
	if err := writeEnvFile(values); err != nil {
		writeError(w, http.StatusBadGateway, "Proměnné nelze bezpečně uložit.")
		return
	}
	a.audit(r, "env_"+req.Action, req.Key, "ok")
	writeJSON(w, http.StatusOK, map[string]string{"ok": "true", "reload": "Restart WebUI pro načtení nové hodnoty."})
}

func writeEnvFile(values map[string]string) error {
	if err := os.MkdirAll(filepath.Dir(envFilePath), 0700); err != nil {
		return err
	}
	keys := make([]string, 0, len(values))
	for k := range values {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var content strings.Builder
	for _, k := range keys {
		if !allowedManagedEnvKey(k) || strings.ContainsAny(values[k], "\r\n\x00") {
			return fmt.Errorf("invalid environment entry")
		}
		if _, err := fmt.Fprintf(&content, "%s=%s\n", k, values[k]); err != nil {
			return err
		}
	}
	return atomicWrite(envFilePath, []byte(content.String()), 0600)
}
