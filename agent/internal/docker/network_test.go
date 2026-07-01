package docker

import (
	"testing"
	"time"

	"github.com/docker/docker/api/types/network"
)

func TestBuildCreateNetworkOptions_DefaultsDriverToBridge(t *testing.T) {
	opts := buildCreateNetworkOptions("", "", "", false)

	if opts.Driver != "bridge" {
		t.Fatalf("empty driver should default to bridge, got %q", opts.Driver)
	}
	if opts.IPAM != nil {
		t.Fatalf("no subnet should produce nil IPAM, got %+v", opts.IPAM)
	}
	if opts.Internal {
		t.Fatalf("internal should be false")
	}
}

func TestBuildCreateNetworkOptions_WithSubnetAndGateway(t *testing.T) {
	opts := buildCreateNetworkOptions("bridge", "172.30.0.0/16", "172.30.0.1", true)

	if opts.IPAM == nil || len(opts.IPAM.Config) != 1 {
		t.Fatalf("expected one IPAM config, got %+v", opts.IPAM)
	}
	cfg := opts.IPAM.Config[0]
	if cfg.Subnet != "172.30.0.0/16" {
		t.Fatalf("subnet: got %q", cfg.Subnet)
	}
	if cfg.Gateway != "172.30.0.1" {
		t.Fatalf("gateway: got %q", cfg.Gateway)
	}
	if !opts.Internal {
		t.Fatalf("internal should be true")
	}
}

func TestBuildCreateNetworkOptions_SubnetWithoutGateway(t *testing.T) {
	opts := buildCreateNetworkOptions("macvlan", "10.0.0.0/24", "", false)

	if opts.Driver != "macvlan" {
		t.Fatalf("driver: got %q", opts.Driver)
	}
	if opts.IPAM == nil || opts.IPAM.Config[0].Subnet != "10.0.0.0/24" {
		t.Fatalf("expected subnet config, got %+v", opts.IPAM)
	}
	if opts.IPAM.Config[0].Gateway != "" {
		t.Fatalf("gateway should be empty, got %q", opts.IPAM.Config[0].Gateway)
	}
}

func TestNetworkInfoFromInspect_ExtractsFields(t *testing.T) {
	created := time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)
	n := network.Inspect{
		ID:       "abc123def456789aaaaaaaaaaaaaaaaaaaaa",
		Name:     "my-net",
		Driver:   "bridge",
		Scope:    "local",
		Created:  created,
		Internal: false,
		IPAM:     network.IPAM{Config: []network.IPAMConfig{{Subnet: "172.20.0.0/16"}}},
		Containers: map[string]network.EndpointResource{
			"containerfullid0000000000000000000000": {Name: "/web"},
		},
	}

	info := networkInfoFromInspect(n)

	if info.ID != "abc123def456" {
		t.Fatalf("id should be 12-char short, got %q", info.ID)
	}
	if info.Subnet != "172.20.0.0/16" {
		t.Fatalf("subnet: got %q", info.Subnet)
	}
	if info.Created != "2026-01-02T03:04:05Z" {
		t.Fatalf("created should be ISO8601 Z, got %q", info.Created)
	}
	if info.ContainerCount != 1 || len(info.Containers) != 1 {
		t.Fatalf("expected 1 container, got %d", info.ContainerCount)
	}
	if info.Containers[0].Name != "web" {
		t.Fatalf("container name prefix should be stripped, got %q", info.Containers[0].Name)
	}
	if info.Containers[0].ID != "containerful" {
		t.Fatalf("container id should be 12-char short, got %q", info.Containers[0].ID)
	}
	if info.IsBuiltin {
		t.Fatalf("my-net should not be builtin")
	}
}

func TestNetworkInfoFromInspect_FlagsBuiltinAndNoSubnet(t *testing.T) {
	n := network.Inspect{ID: "hostnet00", Name: "host", Driver: "host"}

	info := networkInfoFromInspect(n)

	if !info.IsBuiltin {
		t.Fatalf("host should be flagged builtin")
	}
	if info.Subnet != "" {
		t.Fatalf("no IPAM config should yield empty subnet, got %q", info.Subnet)
	}
	if info.ContainerCount != 0 {
		t.Fatalf("expected 0 containers, got %d", info.ContainerCount)
	}
}
