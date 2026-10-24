# Design references

Primary sources inspected for this implementation:

* [PAR2 2.0 format specification](https://parchive.sourceforge.net/docs/specifications/parity-volume-spec/article-spec.html):
  packets, file descriptions, block recovery and safe handling of embedded names.
  The application checks packet hashes and rejects unsupported naming extensions
  before invoking the engine. Repair mathematics remains upstream's responsibility.
* [par2cmdline upstream](https://github.com/Parchive/par2cmdline) and its
  [v0.8.1 source](https://github.com/Parchive/par2cmdline/tree/v0.8.1): established
  create/verify/repair engine. The downloaded source archive SHA-256 is
  `7b2fcc19b54c7080939fc2cbaca33ae40ac33759a526292933c94a85ba850d11`.
  The build source contains the command-line documentation and upstream tests.
  It is built locally, not bundled into this repository.
* [MultiPar](https://github.com/Yutaka-Sawada/MultiPar): existing desktop PAR
  recovery application. This project focuses on a bounded local browser workflow,
  separate staging and independently checked reports, rather than replacing its
  broad desktop feature set or making a novelty claim.
* [Twemoji at the pinned revision](https://github.com/twitter/twemoji/tree/7a3dad4a4da30497093dab22eafba135f02308e1):
  real redistributable artwork input. [Graphics license evidence](https://github.com/twitter/twemoji/blob/7a3dad4a4da30497093dab22eafba135f02308e1/LICENSE-GRAPHICS)
  is archived unchanged in `data/LICENSE-GRAPHICS`. Graphics are CC BY 4.0,
  attributed to Twitter and other contributors; no changes to the bundled SVGs.

PAR2 block redundancy is useful for bounded damage but is not a guarantee about
an arbitrary fraction of modified bytes. A changed byte in each of many blocks
can require many recovery blocks. The experiment therefore states exact damage
operations and expected outcomes instead of estimating a generic recovery rate.
