package main

import (
	"flag"
	"fmt"
	"os"
)

var version = "0.1.0"

func main() {
	wsURL := flag.String("url", "ws://127.0.0.1:9090", "Engine WebSocket URL")
	showVersion := flag.Bool("version", false, "Show version")
	flag.Parse()

	if *showVersion {
		fmt.Printf("ARCHIE Code CLI v%s\n", version)
		os.Exit(0)
	}

	_ = wsURL
	fmt.Printf("ARCHIE Code CLI v%s\n", version)
	fmt.Println("(TUI not yet wired)")
}
