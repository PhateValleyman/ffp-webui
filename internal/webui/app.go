package webui

import (
	"crypto/rand"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

//go:embed assets/*
var webFiles embed.FS

type Config struct {
	ListenAddr             string   `json:"listen_addr"`
	AllowUnauthenticated   bool     `json:"allow_unauthenticated"`
	DemoMode               bool     `json:"demo_mode"`
	AllowedRoots           []string `json:"allowed_roots"`
	PackageRoots           []string `json:"package_roots"`
	StateDir               string   `json:"state_dir"`
	MaxUploadBytes         int64    `json:"max_upload_bytes"`
	MaxPackageBytes        int64    `json:"max_package_bytes"`
	OperationTimeoutSecond int      `json:"operation_timeout_seconds"`
}

func DefaultConfig() Config {
	return Config{
		ListenAddr:             "192.168.1.20:8888",
		AllowUnauthenticated:   true,
		AllowedRoots:           []string{"/ffp"},
		PackageRoots:           []string{"/ffp/pkg", "/ffp/var/tmp/ffp-webui/packages"},
		StateDir:               "/ffp/var/ffp-webui",
		MaxUploadBytes:         32 << 20,
		MaxPackageBytes:        256 << 20,
		OperationTimeoutSecond: 300,
	}
}

func LoadConfig(path string) (Config, error) {
	cfg := DefaultConfig()
	b, err := os.ReadFile(path)
	if err != nil {
		return cfg, err
	}
	if err := json.Unmarshal(b, &cfg); err != nil {
		return cfg, err
	}
	return cfg, cfg.Validate()
}

func (c Config) Validate() error {
	host, port, err := net.SplitHostPort(c.ListenAddr)
	if err != nil {
		return fmt.Errorf("listen_addr musí mít tvar IP:port: %w", err)
	}
	ip := net.ParseIP(host)
	if ip == nil {
		return errors.New("listen_addr musí být konkrétní IP adresa; názvy hostů a wildcard nejsou povoleny")
	}
	if port == "" {
		return errors.New("chybí port posluchače")
	}
	portNumber, err := strconv.Atoi(port)
	if err != nil || portNumber < 1 || portNumber > 65535 {
		return errors.New("port musí být číslo v rozsahu 1–65535")
	}
	if !c.DemoMode && !ip.IsLoopback() {
		if !c.AllowUnauthenticated {
			return errors.New("vzdálený bind bez autentizace je zakázán; explicitně nastav allow_unauthenticated=true pouze pro důvěryhodnou soukromou LAN")
		}
		if !ip.IsPrivate() {
			return errors.New("WebUI bez přihlášení smí poslouchat jen na soukromé IP adrese; nepoužívejte veřejný bind")
		}
	}
	if c.MaxUploadBytes <= 0 || c.MaxUploadBytes > 64<<20 {
		return errors.New("max_upload_bytes musí být mezi 1 a 67108864")
	}
	if c.MaxPackageBytes <= 0 || c.MaxPackageBytes > 512<<20 {
		return errors.New("max_package_bytes musí být mezi 1 a 536870912")
	}
	if c.OperationTimeoutSecond < 10 || c.OperationTimeoutSecond > 1800 {
		return errors.New("operation_timeout_seconds musí být 10–1800")
	}
	if len(c.AllowedRoots) == 0 {
		return errors.New("allowed_roots nesmí být prázdné")
	}
	for _, root := range c.AllowedRoots {
		if !filepath.IsAbs(root) {
			return fmt.Errorf("kořenová cesta není absolutní: %s", root)
		}
		if filepath.Clean(root) == "/" {
			return errors.New("povolený kořenový adresář nesmí být /")
		}
	}
	if c.StateDir != "" && !filepath.IsAbs(c.StateDir) {
		return errors.New("state_dir musí být absolutní cesta")
	}
	for _, root := range c.PackageRoots {
		if !filepath.IsAbs(root) || filepath.Clean(root) == "/" {
			return fmt.Errorf("package root musí být absolutní a nesmí být /: %s", root)
		}
	}
	return nil
}

type App struct {
	cfg          Config
	jobs         *jobStore
	mux          *http.ServeMux
	log          *log.Logger
	requestSlots chan struct{}
}

func New(cfg Config) (*App, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	if cfg.StateDir == "" {
		cfg.StateDir = "/ffp/var/ffp-webui"
	}
	if !cfg.DemoMode {
		if err := os.MkdirAll(cfg.StateDir, 0700); err != nil {
			return nil, fmt.Errorf("nelze vytvořit state_dir %s: %w", cfg.StateDir, err)
		}
	}
	logFile := io.Discard
	if !cfg.DemoMode {
		if err := os.MkdirAll(filepath.Join(cfg.StateDir, "backups"), 0700); err != nil {
			return nil, err
		}
		f, err := os.OpenFile(filepath.Join(cfg.StateDir, "audit.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
		if err != nil {
			return nil, fmt.Errorf("nelze otevřít auditní log: %w", err)
		}
		logFile = f
	}
	a := &App{cfg: cfg, jobs: newJobStore(), log: log.New(logFile, "", log.LstdFlags|log.LUTC), mux: http.NewServeMux(), requestSlots: make(chan struct{}, 8)}
	a.routes()
	return a, nil
}

func (a *App) Handler() http.Handler { return a.securityHeaders(a.limitConcurrent(a.mux)) }

func (a *App) limitConcurrent(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case a.requestSlots <- struct{}{}:
			defer func() { <-a.requestSlots }()
			next.ServeHTTP(w, r)
		default:
			writeError(w, http.StatusServiceUnavailable, "WebUI je zaneprázdněné; zkuste požadavek později.")
		}
	})
}

func (a *App) routes() {
	a.mux.HandleFunc("GET /", a.serveIndex)
	a.mux.HandleFunc("GET /assets/", a.serveAsset)
	a.mux.HandleFunc("GET /api/health", a.handleHealth)
	a.mux.HandleFunc("GET /api/system", a.handleSystem)
	a.mux.HandleFunc("GET /api/services", a.handleServices)
	a.mux.HandleFunc("POST /api/services/action", a.handleServiceAction)
	a.mux.HandleFunc("GET /api/env", a.handleEnvGet)
	a.mux.HandleFunc("POST /api/env", a.handleEnvPost)
	a.mux.HandleFunc("GET /api/files", a.handleFilesList)
	a.mux.HandleFunc("GET /api/files/download", a.handleFileDownload)
	a.mux.HandleFunc("GET /api/files/read", a.handleFileRead)
	a.mux.HandleFunc("POST /api/files/save", a.handleFileSave)
	a.mux.HandleFunc("POST /api/files/upload", a.handleFileUpload)
	a.mux.HandleFunc("POST /api/files/delete", a.handleFileDelete)
	a.mux.HandleFunc("GET /api/packages", a.handlePackagesGet)
	a.mux.HandleFunc("POST /api/packages/upload", a.handlePackageUpload)
	a.mux.HandleFunc("POST /api/packages/fetch", a.handlePackageFetch)
	a.mux.HandleFunc("POST /api/packages/action", a.handlePackageAction)
	a.mux.HandleFunc("GET /api/jobs/", a.handleJobGet)
	a.mux.HandleFunc("GET /api/ssh", a.handleSSHGet)
	a.mux.HandleFunc("GET /api/cron", a.handleCronGet)
	a.mux.HandleFunc("POST /api/cron", a.handleCronPost)
	a.mux.HandleFunc("POST /api/power", a.handlePower)
}

func (a *App) securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
		w.Header().Set("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
		if !a.allowedHost(r.Host) {
			http.Error(w, "Nepovolená hlavička Host", http.StatusMisdirectedRequest)
			return
		}
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			if r.Method != http.MethodPost {
				http.Error(w, "Metoda není povolena", http.StatusMethodNotAllowed)
				return
			}
			if !a.sameOrigin(r) {
				http.Error(w, "Požadavek musí pocházet ze stejného originu", http.StatusForbidden)
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}

func (a *App) allowedHost(raw string) bool {
	return strings.EqualFold(strings.TrimSpace(raw), a.cfg.ListenAddr)
}

func (a *App) sameOrigin(r *http.Request) bool {
	raw := r.Header.Get("Origin")
	if raw == "" {
		raw = r.Header.Get("Referer")
	}
	if raw == "" {
		return true
	}
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" {
		return false
	}
	return strings.EqualFold(u.Host, r.Host) && (u.Scheme == "http" || u.Scheme == "https")
}

func (a *App) serveIndex(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	b, err := webFiles.ReadFile("assets/index.html")
	if err != nil {
		http.Error(w, "Chybí UI asset", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	_, _ = w.Write(b)
}

func (a *App) serveAsset(w http.ResponseWriter, r *http.Request) {
	name := strings.TrimPrefix(filepath.Clean(r.URL.Path), "/")
	if !strings.HasPrefix(name, "assets/") || strings.Contains(name, "..") {
		http.Error(w, "Neplatná cesta", http.StatusBadRequest)
		return
	}
	b, err := webFiles.ReadFile(name)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	switch filepath.Ext(name) {
	case ".js":
		w.Header().Set("Content-Type", "text/javascript; charset=utf-8")
	case ".css":
		w.Header().Set("Content-Type", "text/css; charset=utf-8")
	case ".png":
		w.Header().Set("Content-Type", "image/png")
	default:
		w.Header().Set("Content-Type", "application/octet-stream")
	}
	_, _ = w.Write(b)
}

func (a *App) handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"ok": true, "demo": a.cfg.DemoMode, "authentication": "disabled", "warning": "LAN users can administer this device"})
}

func (a *App) requireLive(w http.ResponseWriter) bool {
	if !a.cfg.DemoMode {
		return true
	}
	writeError(w, http.StatusLocked, "Demo režim je pouze pro náhled; změny jsou vypnuté.")
	return false
}

func (a *App) audit(r *http.Request, action, target, result string) {
	remote := r.RemoteAddr
	if host, _, err := net.SplitHostPort(remote); err == nil {
		remote = host
	}
	// Audit records contain the caller address and action, never submitted values or credentials.
	a.log.Printf("remote=%q action=%q target=%q result=%q", remote, action, target, result)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}

func decodeJSON(w http.ResponseWriter, r *http.Request, dst any, max int64) error {
	r.Body = http.MaxBytesReader(w, r.Body, max)
	defer r.Body.Close()
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	return dec.Decode(dst)
}

func randomID() string {
	var b [12]byte
	if _, err := rand.Read(b[:]); err != nil {
		return fmt.Sprintf("%d", time.Now().UnixNano())
	}
	return hex.EncodeToString(b[:])
}

func (a *App) operationTimeout() time.Duration {
	return time.Duration(a.cfg.OperationTimeoutSecond) * time.Second
}

func (a *App) statePath(parts ...string) string {
	joined := append([]string{a.cfg.StateDir}, parts...)
	return filepath.Join(joined...)
}

func allowedName(s string) bool {
	if s == "" || s == "." || s == ".." || strings.ContainsAny(s, "/\\\x00") {
		return false
	}
	for _, r := range s {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || strings.ContainsRune("._-", r)) {
			return false
		}
	}
	return true
}

func safeError(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}
