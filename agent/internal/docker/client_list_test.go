package docker

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/docker/docker/client"
)

var (
	imageA = "sha256:" + strings.Repeat("a", 64)
	imageB = "sha256:" + strings.Repeat("b", 64)
)

// fakeDocker serves just the endpoints ListContainers calls. images maps an image ID to its
// inspect body; a missing ID answers 404, and failNext makes the next inspect of that ID answer 500.
type fakeDocker struct {
	mu         sync.Mutex
	containers []map[string]any
	images     map[string]map[string]any
	failNext   map[string]bool
	inspects   map[string]int
}

func (f *fakeDocker) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	path := r.URL.Path
	if i := strings.Index(path[1:], "/"); strings.HasPrefix(path, "/v1.") && i >= 0 {
		path = path[i+1:]
	}
	w.Header().Set("Content-Type", "application/json")
	f.mu.Lock()
	defer f.mu.Unlock()
	switch {
	case path == "/containers/json":
		_ = json.NewEncoder(w).Encode(f.containers)
	case strings.HasPrefix(path, "/images/") && strings.HasSuffix(path, "/json"):
		id := strings.TrimSuffix(strings.TrimPrefix(path, "/images/"), "/json")
		f.inspects[id]++
		if f.failNext[id] {
			delete(f.failNext, id)
			w.WriteHeader(http.StatusInternalServerError)
			_, _ = w.Write([]byte(`{"message":"daemon busy"}`))
			return
		}
		body, ok := f.images[id]
		if !ok {
			w.WriteHeader(http.StatusNotFound)
			_, _ = w.Write([]byte(`{"message":"No such image"}`))
			return
		}
		_ = json.NewEncoder(w).Encode(body)
	case strings.HasPrefix(path, "/containers/") && strings.HasSuffix(path, "/json"):
		_, _ = w.Write([]byte(`{"State":{"StartedAt":"2026-11-09T10:00:00Z"},"Config":{"Env":[]}}`))
	default:
		http.NotFound(w, r)
	}
}

func newFakeDockerClient(t *testing.T, fake *fakeDocker) *Client {
	t.Helper()
	if fake.inspects == nil {
		fake.inspects = map[string]int{}
	}
	if fake.failNext == nil {
		fake.failNext = map[string]bool{}
	}
	srv := httptest.NewServer(fake)
	t.Cleanup(srv.Close)
	cli, err := client.NewClientWithOpts(client.WithHost("tcp://"+strings.TrimPrefix(srv.URL, "http://")),
		client.WithVersion("1.43"), client.WithHTTPClient(srv.Client()))
	if err != nil {
		t.Fatalf("client: %v", err)
	}
	c := newCacheClient()
	c.cli = cli
	return c
}

func listedContainer(id, imageID string) map[string]any {
	return map[string]any{"Id": id, "ImageID": imageID, "Names": []string{"/" + id}, "State": "running"}
}

func listPlatforms(t *testing.T, c *Client) map[string]*ImagePlatform {
	t.Helper()
	listed, err := c.ListContainers(context.Background())
	if err != nil {
		t.Fatalf("ListContainers: %v", err)
	}
	platforms := map[string]*ImagePlatform{}
	for _, ctr := range listed {
		platforms[ctr.ID] = ctr.ImagePlatform
	}
	return platforms
}

func TestListContainersReportsTheImagePlatform(t *testing.T) {
	fake := &fakeDocker{
		containers: []map[string]any{listedContainer("c1", imageA), listedContainer("c2", imageA), listedContainer("c3", imageB)},
		images: map[string]map[string]any{
			imageA: {"Id": imageA, "RepoDigests": []string{}, "Os": "linux", "Architecture": "arm", "Variant": "v7"},
			imageB: {"Id": imageB, "RepoDigests": []string{}, "Os": "linux", "Architecture": "amd64"},
		},
	}
	platforms := listPlatforms(t, newFakeDockerClient(t, fake))

	want := map[string]ImagePlatform{
		"c1": {Os: "linux", Architecture: "arm", Variant: "v7"},
		"c2": {Os: "linux", Architecture: "arm", Variant: "v7"},
		"c3": {Os: "linux", Architecture: "amd64"},
	}
	for id, w := range want {
		if got := platforms[id]; got == nil || *got != w {
			t.Errorf("%s: got %+v, want %+v", id, got, w)
		}
	}
	if fake.inspects[imageA] != 1 {
		t.Errorf("containers sharing an image should share one inspect, got %d", fake.inspects[imageA])
	}
}

func TestListContainersSendsNullPlatformForAMissingImage(t *testing.T) {
	fake := &fakeDocker{containers: []map[string]any{listedContainer("c1", imageA)}}
	c := newFakeDockerClient(t, fake)

	listed, err := c.ListContainers(context.Background())
	if err != nil {
		t.Fatalf("ListContainers: %v", err)
	}
	if listed[0].ImagePlatform != nil {
		t.Fatalf("got %+v for an image that is gone", listed[0].ImagePlatform)
	}
	sent, _ := json.Marshal(listed[0])
	var payload map[string]json.RawMessage
	_ = json.Unmarshal(sent, &payload)
	if raw, ok := payload["ImagePlatform"]; !ok || string(raw) != "null" {
		t.Errorf("the backend tells a lost image from an older agent by an explicit null, got %s", sent)
	}
}

func TestListContainersRetriesAFailedImageInspectNextCycle(t *testing.T) {
	fake := &fakeDocker{
		containers: []map[string]any{listedContainer("c1", imageA)},
		images:     map[string]map[string]any{imageA: {"Id": imageA, "Os": "linux", "Architecture": "amd64"}},
		failNext:   map[string]bool{imageA: true},
	}
	c := newFakeDockerClient(t, fake)

	if p := listPlatforms(t, c)["c1"]; p != nil {
		t.Fatalf("first cycle: got %+v from a failed inspect", p)
	}
	if p := listPlatforms(t, c)["c1"]; p == nil || p.Architecture != "amd64" {
		t.Errorf("second cycle: got %+v, want the platform once the inspect succeeds", p)
	}
}

func TestListContainersReportsAPodmanImagePlatform(t *testing.T) {
	fake := &fakeDocker{
		containers: []map[string]any{listedContainer("c1", imageA)},
		images:     map[string]map[string]any{imageA: {"Id": imageA, "Os": "linux", "Architecture": "arm64", "RepoDigests": nil}},
	}
	got := listPlatforms(t, newFakeDockerClient(t, fake))["c1"]
	if got == nil || *got != (ImagePlatform{Os: "linux", Architecture: "arm64"}) {
		t.Errorf("got %+v", got)
	}
}
