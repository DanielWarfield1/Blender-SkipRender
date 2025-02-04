# Blender-SkipRender
An accelerated workflow for rapidly rendering animations with many static frames.

## Installation
 - download this repo as a zip
 - install it as an addon in blender
There will be a new panel in the render settings titled "Skip Renderer"

## Usage
 - specify the top level output directory. Skip Renderer will automatically create sub-directories based on the scene being rendered (to be compatible with Daniel's workflow in making IAEE videos).
 - Skip Renderer uses F-curves for objects and material nodes to approximate static frames. You can analyze at the location of the playhead, or the entire scene, to get an idea of how many duplicate frames SkipRenderer thinks there is.
 - when you begin processing skip renderer will:
    1. create a new folder based on the name of your scene
    2. will copy the audio of the scene into a file `audio.flac`
    3. will create a folder for images
    4. will either render out new images or copy old images, to render out the image sequence that is your scene.
    5. an accurate progress percentage and very inaccurate ETA will be provided.
    6. you can also open whatever folder you specified as the output directory with the "Open Folder" button.

# Note:
- Especially if you're developing, launching blender from the terminal will allow you to view SkipRender output.
- If you do want to contribute, the following would be appreciated:
    1. better ETA approximation
    2. that's it. Otherwise it's perfect in every way, for I am infallible.