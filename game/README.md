# Supply your own game

No game data is distributed with Parappa Access. Place your own US
PaRappa the Rapper (SCUS-94183) dump here, or select it from another folder
during first-run setup. Select the `.ccd` file and keep the matching `.img`
and `.sub` files alongside it. For example:

- `Parappa the Rapper [U] [SCUS-94183].ccd`
- `Parappa the Rapper [U] [SCUS-94183].img`
- `Parappa the Rapper [U] [SCUS-94183].sub`

Keep the original files together, with their descriptor references intact.
This README is the only file in this directory included in Git.

DuckStation itself recognizes IMG, ISO, CUE/BIN, CCD and other formats, but
Parappa Access currently validates and launches the above CCD set. An ISO
extension alone does not establish a complete or compatible dump. Do not
rename an ISO to IMG or convert your dump just to pass this check. Validation
for other formats remains future work.

Format reference: [DuckStation image loader](https://github.com/stenzek/duckstation/blob/master/src/util/cd_image.cpp).
