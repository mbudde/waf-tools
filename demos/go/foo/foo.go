package foo

import "bar"

func Foo() string	{ return bar.Bar() + "!" }
