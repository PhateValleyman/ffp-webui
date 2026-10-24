package webui

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

type SSHInfo struct {
	SSHAvailable   bool     `json:"ssh_available"`
	SSHDAvailable  bool     `json:"sshd_available"`
	SSHFSAvailable bool     `json:"sshfs_available"`
	ConfigPath     string   `json:"config_path,omitempty"`
	SSHFSFSTab     []string `json:"sshfs_mounts"`
	Mode           string   `json:"mode"`
	Note           string   `json:"note"`
}

func (a *App) handleSSHGet(w http.ResponseWriter, r *http.Request) {
	info := SSHInfo{Mode: "read-only discovery", Note: "Konfigurace se zobrazuje přes Správce souborů. Přepis SSH/SSHD, reload a SSHFS mounty zůstanou vypnuté, dokud agent nepotvrdí skutečné cesty, příkazy a možnost obnovy SSH."}
	if a.cfg.DemoMode {
		info.Note = "Ukázkový režim: přítomnost ssh/sshd/sshfs na cílovém NAS není ověřena."
		writeJSON(w, http.StatusOK, info)
		return
	}
	info.SSHAvailable = commandExists("ssh")
	info.SSHDAvailable = commandExists("sshd")
	info.SSHFSAvailable = commandExists("sshfs")
	for _, path := range []string{"/ffp/etc/ssh/sshd_config", "/ffp/etc/sshd_config"} {
		if fi, err := os.Lstat(path); err == nil && fi.Mode().IsRegular() && fi.Mode()&os.ModeSymlink == 0 {
			info.ConfigPath = path
			break
		}
	}
	if b, err := os.ReadFile("/proc/mounts"); err == nil {
		for _, line := range strings.Split(string(b), "\n") {
			if strings.Contains(strings.ToLower(line), "sshfs") {
				info.SSHFSFSTab = append(info.SSHFSFSTab, line)
			}
		}
	}
	writeJSON(w, http.StatusOK, info)
}

func commandExists(name string) bool {
	if _, err := exec.LookPath(name); err == nil {
		return true
	}
	for _, p := range []string{filepath.Join("/ffp/bin", name), filepath.Join("/ffp/sbin", name), filepath.Join("/usr/bin", name), filepath.Join("/usr/sbin", name), filepath.Join("/bin", name), filepath.Join("/sbin", name)} {
		if fi, err := os.Stat(p); err == nil && fi.Mode().IsRegular() && fi.Mode().Perm()&0111 != 0 {
			return true
		}
	}
	return false
}

func (a *App) handleCronGet(w http.ResponseWriter, r *http.Request) {
	if a.cfg.DemoMode {
		writeJSON(w, http.StatusOK, map[string]any{"available": false, "entries": 0, "managed": 0, "note": "Cron je pouze ukázkový. Aktuální crond, crontab i boot persistence nejsou ověřeny."})
		return
	}
	if !commandExists("crontab") {
		writeJSON(w, http.StatusOK, map[string]any{"available": false, "entries": 0, "managed": 0, "note": "Příkaz crontab nebyl nalezen."})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "crontab", "-l")
	out, err := cmd.Output()
	if err != nil {
		writeJSON(w, http.StatusOK, map[string]any{"available": true, "entries": 0, "managed": 0, "note": "crontab -l selhal nebo neexistuje crontab. Text příkazu není vystaven přes neautentizované UI."})
		return
	}
	entries := 0
	for _, line := range strings.Split(string(out), "\n") {
		trimmed := strings.TrimSpace(line)
		if trimmed != "" && !strings.HasPrefix(trimmed, "#") {
			entries++
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"available": true, "entries": entries, "managed": 0, "note": "Pouze read-only počet úloh. Editor libovolných cron příkazů není aktivní, protože by neautentizovanému klientovi poskytl trvalé spuštění libovolného kódu jako root."})
}

func (a *App) handleCronPost(w http.ResponseWriter, r *http.Request) {
	writeError(w, http.StatusNotImplemented, "Změny cronu nejsou v této verzi povoleny. Nejprve je třeba ověřit crond, persistence po rebootu a bezpečný seznam přednastavených úloh.")
}

func (a *App) handlePower(w http.ResponseWriter, r *http.Request) {
	if !a.requireLive(w) {
		return
	}
	var req struct {
		Action  string `json:"action"`
		Confirm string `json:"confirm"`
	}
	if err := decodeJSON(w, r, &req, 4096); err != nil {
		writeError(w, http.StatusBadRequest, "Neplatný JSON požadavek.")
		return
	}
	var binary, phrase string
	switch req.Action {
	case "restart":
		binary, phrase = "/sbin/reboot", "REBOOT NSA320"
	case "shutdown":
		binary, phrase = "/sbin/poweroff", "SHUTDOWN NSA320"
	default:
		writeError(w, http.StatusBadRequest, "Povolené akce jsou restart a shutdown.")
		return
	}
	if req.Confirm != phrase {
		writeError(w, http.StatusBadRequest, "Chybí přesné potvrzení akce a cílového zařízení.")
		return
	}
	if _, err := os.Stat(binary); err != nil {
		writeError(w, http.StatusServiceUnavailable, "Odpovídající systémový příkaz nebyl nalezen na očekávané cestě; nic nebylo provedeno.")
		return
	}
	a.audit(r, "power_"+req.Action, "NSA320", "scheduled")
	go func() {
		time.Sleep(2 * time.Second)
		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		cmd := exec.CommandContext(ctx, binary)
		cmd.Env = []string{"PATH=/ffp/bin:/ffp/sbin:/bin:/sbin", "HOME=/ffp/home/root", "LANG=C"}
		if out, err := cmd.CombinedOutput(); err != nil {
			a.log.Printf("action=power_%s result=failed err=%q output=%q", req.Action, err.Error(), limitedText(out))
		}
	}()
	writeJSON(w, http.StatusAccepted, map[string]string{"ok": "true", "message": "Příkaz bude spuštěn za 2 sekundy. Bez autentizace může tuto akci vyvolat kterýkoli klient v LAN."})
}

var _ = fmt.Sprintf
