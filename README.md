# Blender-SkipRender
An accelerated render workflow for creating diagram video with transparent backgrounds in Blender.

## dependencies
- [blender](https://www.blender.org/)
- [ffmpeg](https://www.ffmpeg.org/)

## instructions
1. install [dependencies](#dependencies)
2. clone the repository
3. cd into `Blender-SkipRender`
4. run `blender <path/to/file.blend> --background --python script.py -- <path/to/output/directory>`
5. enjoy faster rendering!

## limitations
- only updates frames when location, rotation, or scale change
