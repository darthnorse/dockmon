package handlers

import (
	"net/http"
	"reflect"
	"testing"
)

func TestHealthCheckTransportHonorsProxyEnvironment(t *testing.T) {
	for _, skip := range []bool{false, true} {
		tr := newHealthCheckTransport(skip)
		if tr.Proxy == nil || reflect.ValueOf(tr.Proxy).Pointer() != reflect.ValueOf(http.ProxyFromEnvironment).Pointer() {
			t.Fatalf("insecureSkipVerify=%v: health-check transport must use http.ProxyFromEnvironment", skip)
		}
	}
}
