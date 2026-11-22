package util

import "example.com/fixtureapp/internal/shared"

// Greet returns the shared greeting.
func Greet() string {
	return shared.Name()
}
