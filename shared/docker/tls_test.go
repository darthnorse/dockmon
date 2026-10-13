package docker

import (
	"crypto/tls"
	"net/http"
	"reflect"
	"testing"
)

func TestTLSTransportHonorsProxyEnvironment(t *testing.T) {
	cfg := &tls.Config{MinVersion: tls.VersionTLS12}
	tr := newTLSTransport(cfg)

	if tr.Proxy == nil || reflect.ValueOf(tr.Proxy).Pointer() != reflect.ValueOf(http.ProxyFromEnvironment).Pointer() {
		t.Fatal("mTLS transport must use http.ProxyFromEnvironment so HTTP(S)_PROXY/NO_PROXY apply like the plain-TCP path")
	}
	if tr.TLSClientConfig != cfg {
		t.Fatal("mTLS transport must carry the supplied TLS config")
	}
}
