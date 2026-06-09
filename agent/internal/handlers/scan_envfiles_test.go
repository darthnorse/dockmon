package handlers

import (
	"reflect"
	"sort"
	"testing"
)

func TestParseEnvFileRefs(t *testing.T) {
	compose := `
services:
  app:
    env_file: .app.env
  db:
    env_file:
      - .db.env
      - path: ./extra.env
      - ../escape.env
      - /abs/x.env
`
	captured, skipped := parseEnvFileRefs([]byte(compose))
	sort.Strings(captured)
	want := []string{".app.env", ".db.env", "extra.env"}
	if !reflect.DeepEqual(captured, want) {
		t.Errorf("captured = %v, want %v", captured, want)
	}
	sort.Strings(skipped)
	wantSkip := []string{"../escape.env", "/abs/x.env"}
	if !reflect.DeepEqual(skipped, wantSkip) {
		t.Errorf("skipped = %v, want %v", skipped, wantSkip)
	}
}

func TestParseEnvFileRefsSingleLongForm(t *testing.T) {
	compose := `
services:
  solo:
    env_file:
      path: ./solo.env
      required: false
`
	captured, _ := parseEnvFileRefs([]byte(compose))
	if len(captured) != 1 || captured[0] != "solo.env" {
		t.Fatalf("captured = %v, want [solo.env]", captured)
	}
}

func TestParseEnvFileRefsMalformed(t *testing.T) {
	captured, skipped := parseEnvFileRefs([]byte(":\n  bad: ["))
	if captured != nil || skipped != nil {
		t.Fatalf("malformed -> (%v, %v), want (nil, nil)", captured, skipped)
	}
}

func TestParseEnvFileRefsDedup(t *testing.T) {
	compose := `
services:
  a:
    env_file: .shared.env
  b:
    env_file: .shared.env
`
	captured, _ := parseEnvFileRefs([]byte(compose))
	if len(captured) != 1 || captured[0] != ".shared.env" {
		t.Fatalf("captured = %v, want [.shared.env]", captured)
	}
}
