# demo-python (example pack)

A minimal, deliberately **unscored** example pack: it claims no
GhostBench result, so `ghostpacks show` must label it unscored and
`ghostpacks lint` must still pass it.

What it does when merged into a project:

- ignores `generated/**`
- slices `src/**` to signatures mode

It exists so the merge/remove flow in `examples/README.md` can be run
by hand against `examples/fixture-project/`. It is an example, not
one of the shipping starter packs in `packs/`.
