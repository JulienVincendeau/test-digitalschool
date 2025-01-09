package main

import (
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"regexp"
)

func handler(w http.ResponseWriter, r *http.Request) {
	evt := r.URL.Query().Get("evt")
	usecase := r.URL.Query().Get("usecase")
	table := r.URL.Query().Get("table")
	reload := r.URL.Query().Get("reload")
	site := r.URL.Query().Get("site")
	start_date := r.URL.Query().Get("start_date")
	end_date := r.URL.Query().Get("end_date")
	re := regexp.MustCompile(`^_?[a-zA-Z]+[a-zA-Z0-9\-_]*$`)

	if !re.MatchString(evt) {
		log.Fatalf("invalid evt criteria %q, evt required", evt)
	}

	if !re.MatchString(usecase) {
		log.Fatalf("invalid usecase criteria %q, usecase required", usecase)
	}

	if !re.MatchString(table) {
		log.Fatalf("invalid table criteria %q, table required", table)
	}

	if !re.MatchString(reload) {
		log.Fatalf("invalid reload criteria %q, reload required", reload)
	}

	log.Print("Python Run: received a request")
	cmd := exec.Command("/bin/sh", "script.sh", evt, usecase, table, reload, site, start_date, end_date)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	err := cmd.Run()
	if err != nil {
		log.Fatalf("cmd.Run() failed with %s\n", err)
		}
	}

func main() {
	log.Print("Python Run: starting server...")
	http.HandleFunc("/", handler)
	port := os.Getenv("PORT")
	if port == "" {
			port = "8080"
	}
	log.Printf("Python Run: listening on %s", port)
	log.Fatal(http.ListenAndServe(fmt.Sprintf(":%s", port), nil))
}