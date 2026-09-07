# The product film

Five scenes, recorded from the real editor against a real run, then stitched
into one file for the landing page.

## Record

    npx playwright test --config playwright.demo.config.ts

The configuration starts its own backend on port 8126, so a recording never
competes with a development server on 5273 or 8123. Scene 5 makes a real model
call against Ollama cloud. The configuration blanks `OLLAMA_HOST` and
`OLLAMA_ENDPOINT` so the request reaches the cloud and not a local daemon. The
key comes from `.env`, which the backend loads itself.

Record one scene again after a change:

    npx playwright test --config playwright.demo.config.ts --grep tour

## Stitch

    ./scripts/demo/stitch.sh

The script reads `demo-out/scenes/`, applies the speed in each file name, joins
the scenes, and writes `demo-out/demo.mp4`, `demo-out/demo.webm`,
`demo-out/poster.jpg` and `demo-out/chapters.md`.

## The scenes

| File | Speed | Shows |
| --- | --- | --- |
| `01-tour` | 3x | The palette: packages, tools, node families |
| `02-starter` | 2x | One drag places a wired workflow |
| `03-open` | 2x | A package opens with all its nodes |
| `04-ask` | 2x | The chat takes a typed question |
| `05-answer` | 1x | The live answer, then the run timeline |
| `06-patrol` | 1.5x | A patrol reads that run back and files real cards |

Scene 6 depends on scene 5. A patrol reads recorded runs, so there has to be
one. The findings in the film are real and come from the run scene 5 makes.
`e2e/demo/support/globalSetup.ts` deletes `kanban.sqlite` before a recording so
the board starts empty, and deletes nothing else, so the runs survive when one
scene is recorded on its own.

Speed belongs to the scene. A palette scroll is worth 3x and a model answering
is worth real time, so the film cannot have one rate. The number lives in the
file name, which is also the manifest the stitch script reads.

## Publish

Copy the three output files into `site/media/` and paste
`scripts/demo/embed.html` into the landing page.

    mkdir -p site/media
    cp demo-out/demo.mp4 demo-out/demo.webm site/media/
    cp demo-out/poster.jpg site/media/demo-poster.jpg

The chapter times in `embed.html` come from `demo-out/chapters.md`. Update them
when a scene changes length.
