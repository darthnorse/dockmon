package handlers

import "testing"

func TestDeployComposeRequestHasEnvFiles(t *testing.T) {
	req := DeployComposeRequest{
		EnvFiles: map[string]string{".db.env": "P=1"},
	}
	if req.EnvFiles[".db.env"] != "P=1" {
		t.Fatal("EnvFiles not carried on DeployComposeRequest")
	}
}
