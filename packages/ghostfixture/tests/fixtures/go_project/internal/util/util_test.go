package util

import "testing"

func TestGreet(t *testing.T) {
	if Greet() == "" {
		t.Fatal("empty greeting")
	}
}
