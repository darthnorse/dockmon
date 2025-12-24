package docker

import (
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"net"
	"net/http"
	"time"

	"github.com/docker/docker/client"
)

// CreateTLSClient creates a Docker client with TLS configuration from PEM-encoded certificates
// This is the proven, battle-tested TLS configuration from stats-service
func CreateTLSClient(hostAddress, caCertPEM, certPEM, keyPEM string) (*client.Client, error) {
	tlsOpt, err := createTLSOption(caCertPEM, certPEM, keyPEM)
	if err != nil {
		return nil, err
	}

	return client.NewClientWithOpts(
		client.WithHost(hostAddress),
		client.WithAPIVersionNegotiation(),
		tlsOpt,
	)
}

// createTLSOption creates a Docker client TLS option from PEM-encoded certificates
func createTLSOption(caCertPEM, certPEM, keyPEM string) (client.Opt, error) {
	// Parse CA certificate
	caCertPool := x509.NewCertPool()
	if !caCertPool.AppendCertsFromPEM([]byte(caCertPEM)) {
		return nil, fmt.Errorf("failed to parse CA certificate")
	}

	// Parse client certificate and key
	clientCert, err := tls.X509KeyPair([]byte(certPEM), []byte(keyPEM))
	if err != nil {
		return nil, fmt.Errorf("failed to parse client certificate/key: %v", err)
	}

	// Create TLS config
	tlsConfig := &tls.Config{
		Certificates: []tls.Certificate{clientCert},
		RootCAs:      caCertPool,
		MinVersion:   tls.VersionTLS12,
	}

	// Create HTTP client with TLS transport and timeouts
	// Note: No overall Timeout set because Docker API streaming operations (stats, events)
	// are long-running connections that should not be killed by a timeout
	httpClient := &http.Client{
		Transport: &http.Transport{
			DialContext: (&net.Dialer{
				Timeout:   30 * time.Second, // Connection establishment timeout
				KeepAlive: 30 * time.Second, // TCP keepalive interval
			}).DialContext,
			TLSClientConfig:       tlsConfig,
			TLSHandshakeTimeout:   10 * time.Second,
			IdleConnTimeout:       90 * time.Second,
			ResponseHeaderTimeout: 10 * time.Second,
		},
	}

	return client.WithHTTPClient(httpClient), nil
}

// CreateLocalClient creates a Docker client for local socket
func CreateLocalClient() (*client.Client, error) {
	return client.NewClientWithOpts(
		client.FromEnv,
		client.WithAPIVersionNegotiation(),
	)
}

// CreateRemoteClient creates a Docker client for a remote host
// If TLS credentials are provided, they will be used. Otherwise, plain TCP.
func CreateRemoteClient(hostAddress, caCertPEM, certPEM, keyPEM string) (*client.Client, error) {
	clientOpts := []client.Opt{
		client.WithHost(hostAddress),
		client.WithAPIVersionNegotiation(),
	}

	// If TLS certificates provided, configure TLS
	if caCertPEM != "" && certPEM != "" && keyPEM != "" {
		tlsOpt, err := createTLSOption(caCertPEM, certPEM, keyPEM)
		if err != nil {
			return nil, fmt.Errorf("failed to create TLS config: %v", err)
		}
		clientOpts = append(clientOpts, tlsOpt)
	}

	return client.NewClientWithOpts(clientOpts...)
}
