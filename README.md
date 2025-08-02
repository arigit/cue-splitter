# cue-splitter
A GTK4/libadwaita cuesheet-splitter GUI App, meant to split single-file FLAC into per-track Orgs. 
Depends on ffmpeg, rsgain and other utilities and libraries.

It is meant as a tool for digital audio fans/audiophiles that keep their collection as single-file FLAC files but occasionally 
want to export "ogg" files for their digial audio player.

It handles 24-bit / high bit rate sources with no issue.

It will tag the generated songs based on the cuesheet info; the generated songs are created in a new directory named after the
artist and album name. 

It will also attempt to find the cover art and if it finds it, it will create a small 500px x 500px version of it 
in the newly created directory.

It will not touch the source folder or files.

Simple GUI and command line app that can accept drag and drop files from File Manager 
Allows inputting a command line (script and parameters) to be run on each of the URIs secuentially.
Multithreaded: it uses concurrency for the song split and replay gain analysis; shows real time status; logs output.
Integrates well with "nautilus-scripts" to allow right-clicking a cuesheet and splitting it.

Uses Python / PyGI / LibAdwaita (GTK4)

## Coding Style

The coding style is horrible, you have been warned.

Coding started ~20 years ago when I was learning python, and trying to add a linux/gnome GUI to a bash script.

It started as a python2/GTK2 app, then got ported to python3/GTK3, and now it looks much nicer, using GTK4/Libadwaita. 
There are traces of old code and bad code practices all over. 

Feel free to improve it, pull requests are welcome!

<img width="480" height="824" alt="image" src="https://github.com/user-attachments/assets/86790226-c302-40a5-8326-05b35d6a866d" />


## Major Dependencies

Dependencies: 
* python3
* ffmpeg
* flac
* rsgain
* python3-mutagen
* python3-pydub
* python3-chardet

  
