# Tianyi model and action provenance

The model files and the action artifacts under `data/` were copied unchanged
from `~/workspace/services/tianyi-action-recorder` on 2026-09-14. Robot Guide
reads the recorder JSON and NPZ schemas directly; it does not introduce a
second action format.

Included action:

- `concierge_present_left`

Its sequence is
`base/concierge_init -> composed/concierge_present_left -> base/concierge_init`.
The trajectory was compiled at 25 Hz and validated against the pinned Tianyi
model by the recorder.

Model source ID:

```text
xhumanoid_tianyi2_0_pro_body_21dof_5c221783
```

Pinned artifact hashes:

```text
71253d0679248a9bbbfad3c6a7fcde13262088968cdb6f7079e0498ac35df7e8  asset/tianyi2/tianyi2.0_URDF.urdf
f093a3aeeef147b895261aacce13d7579d2a1994951830a950cf7bc1d0b1c603  data/trajectories/concierge_present_left.npz
```

`concierge_speak_1` is deliberately not bundled: its current action JSON is a
2-second sequence while its existing NPZ is a stale 5-second trajectory. Add it
only after regenerating and validating it in `tianyi-action-recorder`.
