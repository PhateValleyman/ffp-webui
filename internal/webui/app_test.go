package webui

import (
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func testConfig(t *testing.T) Config {
	t.Helper()
	root := t.TempDir()
	state := filepath.Join(t.TempDir(), "state")
	return Config{ListenAddr: "127.0.0.1:8888", DemoMode: true, AllowedRoots: []string{root}, PackageRoots: []string{root}, StateDir: state, MaxUploadBytes: 1 << 20, MaxPackageBytes: 2 << 20, OperationTimeoutSecond: 30}
}

func TestConfigRequiresExplicitLANUnauthenticatedFlag(t *testing.T) {
	cfg := DefaultConfig()
	cfg.AllowUnauthenticated = false
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected unauthenticated remote bind to be rejected")
	}
}

func TestConfigRejectsPublicUnauthenticatedBind(t *testing.T) {
	cfg := DefaultConfig()
	cfg.ListenAddr = "8.8.8.8:8888"
	if err := cfg.Validate(); err == nil {
		t.Fatal("expected public address to be rejected")
	}
}

func TestSecurePathAllowsOnlyInsideConfiguredRoot(t *testing.T) {
	cfg := testConfig(t)
	root := cfg.AllowedRoots[0]
	if err := os.WriteFile(filepath.Join(root, "a.txt"), []byte("ok"), 0600); err != nil {
		t.Fatal(err)
	}
	app, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	got, _, err := app.securePath(filepath.Join(root, "a.txt"), false)
	if err != nil {
		t.Fatalf("expected in-root path: %v", err)
	}
	if got != filepath.Join(root, "a.txt") {
		t.Fatalf("unexpected resolved path %q", got)
	}
	if _, _, err := app.securePath(filepath.Join(root, "..", "outside"), false); err == nil {
		t.Fatal("expected traversal path to be rejected")
	}
}

func TestSecurePathRejectsSymlinkEscape(t *testing.T) {
	cfg := testConfig(t)
	root := cfg.AllowedRoots[0]
	outside := t.TempDir()
	if err := os.WriteFile(filepath.Join(outside, "secret.txt"), []byte("secret"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(root, "outside")); err != nil {
		t.Fatal(err)
	}
	app, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := app.securePath(filepath.Join(root, "outside", "secret.txt"), false); err == nil {
		t.Fatal("expected symlink traversal to be rejected")
	}
}

func TestSecurePathSupportsConfiguredRootSymlink(t *testing.T) {
	actual := t.TempDir()
	alias := filepath.Join(t.TempDir(), "ffp")
	if err := os.Symlink(actual, alias); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(actual, "config.txt"), []byte("ok"), 0600); err != nil {
		t.Fatal(err)
	}
	cfg := testConfig(t)
	cfg.AllowedRoots = []string{alias}
	app, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	for _, input := range []string{filepath.Join(alias, "config.txt"), filepath.Join(actual, "config.txt")} {
		got, _, err := app.securePath(input, false)
		if err != nil {
			t.Fatalf("expected FFP alias and resolved path to work, input=%s err=%v", input, err)
		}
		if got != filepath.Join(actual, "config.txt") {
			t.Fatalf("expected canonical path, got %s", got)
		}
	}
}

func TestSensitivePathsAreNotExposed(t *testing.T) {
	if !isSensitivePath("/ffp/etc/ssh/ssh_host_rsa_key") {
		t.Fatal("expected SSH host private key to be protected")
	}
	if !isSensitivePath("/ffp/home/root/.ssh/id_ed25519") {
		t.Fatal("expected user private key to be protected")
	}
	if !isSensitivePath(envFilePath) {
		t.Fatal("expected WebUI environment file to be protected")
	}
	if isSensitivePath("/ffp/etc/ssh/sshd_config") {
		t.Fatal("expected sshd configuration to remain accessible")
	}
}

func TestSameOriginCheck(t *testing.T) {
	app, err := New(testConfig(t))
	if err != nil {
		t.Fatal(err)
	}
	good := httptest.NewRequest("POST", "http://127.0.0.1:8888/api/test", nil)
	good.Host = "127.0.0.1:8888"
	good.Header.Set("Origin", "http://127.0.0.1:8888")
	if !app.sameOrigin(good) {
		t.Fatal("expected same origin to pass")
	}
	bad := httptest.NewRequest("POST", "http://127.0.0.1:8888/api/test", nil)
	bad.Host = "127.0.0.1:8888"
	bad.Header.Set("Origin", "http://evil.example")
	if app.sameOrigin(bad) {
		t.Fatal("expected cross origin to fail")
	}
}

func TestPackageName(t *testing.T) {
	for _, name := range []string{"app-1.0-arm.txz", "pkg.tgz"} {
		if !isPackageName(name) {
			t.Fatalf("expected %s to be accepted", name)
		}
	}
	for _, name := range []string{"../bad.txz", "script.sh", "x;touch.tgz", ""} {
		if isPackageName(name) {
			t.Fatalf("expected %s to be rejected", name)
		}
	}
}
