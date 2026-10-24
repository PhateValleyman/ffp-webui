package main

import (
	"flag"
	"fmt"
	"log"
	"net/http"
	"time"

	"ffp-webui/internal/webui"
)

func main() {
	configPath := flag.String("config", "/ffp/etc/ffp-webui/config.json", "path to JSON configuration")
	checkConfig := flag.Bool("check-config", false, "validate configuration and exit")
	demo := flag.Bool("demo", false, "run a read-only preview bound to 127.0.0.1:8888")
	flag.Parse()

	cfg, err := webui.LoadConfig(*configPath)
	if err != nil {
		log.Fatalf("configuration error: %v", err)
	}
	if *demo {
		cfg.DemoMode = true
		cfg.ListenAddr = "127.0.0.1:8888"
		cfg.AllowUnauthenticated = false
	}
	if err := cfg.Validate(); err != nil {
		log.Fatalf("configuration error: %v", err)
	}
	if *checkConfig {
		fmt.Printf("configuration valid; listen=%s; demo=%t; unauthenticated=%t\n", cfg.ListenAddr, cfg.DemoMode, cfg.AllowUnauthenticated)
		return
	}
	app, err := webui.New(cfg)
	if err != nil {
		log.Fatalf("server setup failed: %v", err)
	}
	server := &http.Server{
		Addr:              cfg.ListenAddr,
		Handler:           app.Handler(),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       11 * time.Minute,
		WriteTimeout:      11 * time.Minute,
		IdleTimeout:       60 * time.Second,
		MaxHeaderBytes:    1 << 20,
	}
	log.Printf("FFP WebUI listening on %s (demo=%t, authentication=disabled)", cfg.ListenAddr, cfg.DemoMode)
	if !cfg.DemoMode && cfg.AllowUnauthenticated {
		log.Printf("SECURITY WARNING: every reachable LAN client can administer this NAS; do not expose this port to the internet")
	}
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("HTTP server failed: %v", err)
	}
}
