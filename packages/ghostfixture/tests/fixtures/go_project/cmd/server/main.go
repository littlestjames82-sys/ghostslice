package main

import (
	"fmt"

	"example.com/fixtureapp/internal/nested"
	"example.com/fixtureapp/internal/util"
)

func main() {
	fmt.Println(util.Greet())
	_ = nested.Value
}
