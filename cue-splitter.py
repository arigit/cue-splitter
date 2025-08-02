#!/usr/bin/python3
# -*- coding: utf-8 -*-
""" Simple GUI and command line app that can accept drag and drop files from File Manager 
 Allows inputting a command line (script and parameters) to be run on each of the URIs 
 secuentially.
 Multithreaded: it uses concurrency for the song split and replay gain analysis; shows real time status; logs output.
 Integrates well with "nautilus-scripts" to allow right-clicking a cuesheet and splitting it.

 Uses Python / PyGI / LibAdwaita (GTK4)
"""

__title__ = "cue-splitter"
__app_name__ = "Cue Splitter"
__app_icon_name__ = "accessories-text-editor-symbolic"
__version__ = "0.4.0"
__author__ = "/ar"
__email__ = ""
__website__ = ""
__copyright__ = "Copyright \xc2\xa9 2008-2025 " + __author__
__license__ = "GPLv3"
__comments__ = "Splits single-file+cuesheet audio images (flac, ape, wv, wav)\nin per-track tagged ogg vorbis, mp3 or flac files"
__debug_mode__ = True

# Script Configuration
default_output_directory = "/media/mediastore1/Audio-Vorbis/Music Library - Vorbis/AA - Nuevos"
testing_mode = False  # will preselect the testing cuesheet and output directory
testing_cuesheet = "/media/mediastorage/Audio-Vorbis/Music Library - Vorbis/AA - Nuevos/base file for tests/CDImage.cue"
testing_output_directory = (
    "/media/mediastorage/Audio-Vorbis/Music Library - Vorbis/AA - Nuevos/base 2 for tests 192k"
)
concurrency_limit = 8 # number of songs being cut at the same time; there is a check in main() for safety
options = "" # global command line options


""" Development Notes
 Input Audio image file format support:
   FLAC: supported in any sample rate and bit depth
   AIFF: supported in any sample rate and bit depth, but must be PCM big endian encoding (ffmpeg limitation)
   WAV:  difficulties supporting 24 bits (ffmpeg only supports little-endian, and 24-bit files can't be probed)
   + any other ffmpeg-supported format

 Output ogg/mp3: downsampling to 44.1Khz will be done if the source was high bit-rate 
                 (output bit depth is not applicable to ogg/mp3)
 Output FLAC: the output will mirror the input in terms of bit depth and sample rate (no downsampling)
 ReplayGain: loudness analysis and replaygain tagging is done on the output files
 The output tracks will be tagged (vorbiscomments or ID3 as applicable) using the cuesheet information
 The song filenames will contain the song names but with no accented characters 
   (to maximize compatibility with portable music players)
 Can handle accented characters in filenames and inside cuesheets (EAC-encoded to ISO_8859, ASCII or UTF-8)
 If the cuesheet folder contains a cover.jpg or cover.front.jpg file, it will be copied to the destination folder
   using the cover.jpg name and a 500x500px size (no matter what the size was of the original cover)

 Presents a GUI if no arguments (or not enough arguments) are passed
 The GUI supports drag & drop of files (cuesheets) from Nautilus

 Usage: cue-splitter.py [options] cuesheet_file
 Options:
  -h, --help            show this help message and exit
  -d DIRECTORY, --output_directory=DIRECTORY
                        write report to DIRECTORY
  -c CODEC, --codec=CODEC
                        specify the codec (output format) [ogg | mp3 | flac],
                        [default: ogg]
  -q QUALITY, --quality=QUALITY
                        specify the quality target for the encoder, [default:
                        6]
  -g, --display-gui     indicates whether to use a Graphical User Interface or
                        not, [default: True]

  Quality: 
     for ogg: quality parameter (default: 6, which is roughly 192Kbps)
     for mp3: VBR average bit rate

 Designed to work as a nautilus-script plugin; this script should be stored or symlinked in: ~/.local/share/nautilus/scripts

 Usage: right-click on .cue on nautilus, launch the script

 Dependencies: python3 ffmpeg flac rsgain nautilus-script-manager
               python3-mutagen (for ogg/id3 tag handling)
               python3-pydub (for audio file info identification)
               python3-chardet

 Change Log
 0.4.0: gtk4/adwaita UI re-write and code cleanup, migrated replay gain to rsgain (multithreaded, massive speedup) (2025)
 0.3.7: added concurrency for the split for a massive 3X-4X speed increase (vorbisgain is still sequential) (2022)
 0.3.6: added replaygain calculation and tagging to the output ogg files using vorbisgain (2019)
 0.3.5: replaced iconv and 'file' with python native chardet; fixed missing '/' and '\\'matching in cleanupTrackFilenames
 0.3.4: switched to high-res timestamps and ffmpeg by-default; validated ffmpeg cutting against foobar at the PCM 
        sample level (md5 audio signature); validated that: flac-joiner(cue-splitter(image_file)) is a truly neutral operation
 0.3.3: added support for ffmpeg-based splitting (alternative to shntool, works better for HD Audio in flac/aiff/wave)
 0.3.2  migration to native PyGI, removal of pygtkcompat, added support for splitting HDAudio FLACs
 0.3.0: migration to GTK3, Python3, Gobject-introspection (via pygtkcompat), update glade components
 0.2.5: added support for single-track CDs
 0.2.4: added [File > Show the Log File] option in the menu; it will open the log file with the gnome default app
 0.2.3: added split-to-FLAC support, reworked GUI to make it smaller to fit nettop-type screens
 0.2.2: added initialization/defaults for cuesheet parser, otherwise if DATE is missing, the parser would crash
 0.2.1.5: added support for covers; if cover.jpg or cover.frong.jpg exists in the source folder, a 500x500 thumbnail
          will be generated
 0.2.1: added split-to-MP3 support; added support for processing multiple cuesheets via drag & drop from nautilus
 0.2.0: full rewrite in python (from bash) (2009)
"""


import sys
import os
import io
import time
import logging, logging.handlers
from optparse import OptionParser
import tempfile
import shutil
import unicodedata
import glob
import sys
from PIL import Image # type: ignore
import subprocess
import itertools
import threading
import chardet
import wave
from pydub.utils import mediainfo # type: ignore
from mutagen.oggvorbis import OggVorbis
from mutagen.flac import FLAC
from mutagen.easyid3 import EasyID3


# remove GTK error noise
def suppress_stderr():
    sys.stderr.flush()
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr_fd = os.dup(2)
    os.dup2(devnull, 2)
    os.close(devnull)
    return old_stderr_fd
if not __debug_mode__: old_stderr_fd = suppress_stderr()

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GObject, GLib, Gdk



class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.set_default_size(450, -1)
        # set app name
        self.set_title(__app_name__)
        GLib.set_application_name(__app_name__)

        # Create the hamburger Menu
        menu = Gio.Menu.new()    
        # Create a popover
        self.popover = Gtk.PopoverMenu()  # Create a new popover menu
        self.popover.set_menu_model(menu)
        # Create a menu button
        self.hamburger = Gtk.MenuButton()
        self.hamburger.set_popover(self.popover)
        self.hamburger.set_icon_name("open-menu-symbolic")  # Give it a nice icon
        # Add a header bar
        self.header = Gtk.HeaderBar()
        self.set_titlebar(self.header)
        # Add menu button to the header bar
        self.header.pack_end(self.hamburger)

        # Menu Items
        # Add an about dialog
        action = Gio.SimpleAction.new("about", None)
        action.connect("activate", self.show_about)
        self.add_action(action) 
        menu.append("About", "win.about")

        # Add Show Log to menu
        action = Gio.SimpleAction.new("show_log", None)
        action.connect("activate", self.show_log_file)
        self.add_action(action) 
        menu.append("Show Log", "win.show_log")

        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", self.quit_app)
        self.add_action(action)  # Here the action is being added to the window instead of the app
        menu.append("Quit", "win.quit")  # action attached to window

        # Main layout containers
        # concept: 
        #   1 Vertical, containing 3 child boxes stacked
        #   box 1_1 containes cuesheet and outfolder selectors
        #   box 1_2 contains out format options
        #   box 1_3 is for batch processing
  
        self.box1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.box1_1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.box1_1.set_margin_top(20)
        self.box1_1.set_margin_start(20)
        self.box1_1.set_margin_end(20)

        self.box1_2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        self.box1_2.set_margin_top(20)
        self.box1_3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.box1_3.set_margin_top(20)
        self.box1_1_1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        self.box1_1_2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        
        self.set_child(self.box1)  # Horizontal box to window
        self.box1.append(self.box1_1)  
        self.box1.append(self.box1_2)  
        self.box1.append(self.box1_3)  
        self.box1_1.append(self.box1_1_1)
        self.box1_1.append(self.box1_1_2)
        

        self.label1 = Gtk.Label()
        self.label1.set_markup("<b>Cuesheet File:</b>")
        self.label1.set_xalign(2)
        self.label1.set_valign(Gtk.Align.CENTER) 
        self.button1 = Gtk.Button(label="Select Cuesheet File")
        self.button1.set_hexpand(True)
        self.button1.connect("clicked", self.on_cuesheet_select_button_clicked)

        self.label2 = Gtk.Label()
        self.label2.set_markup("<b>Output Folder:</b>")
        self.label2.set_valign(Gtk.Align.CENTER) 
        
        default_output_folder_name = os.path.basename(options.output_directory)            
        self.button2 = Gtk.Button(label=default_output_folder_name)
        self.button2.set_tooltip_text("Selected: " + options.output_directory)
        self.button2.set_hexpand(True)
        self.button2.connect("clicked", self.on_output_folder_select_button_clicked)

        self.button3 = Gtk.Button(label="Split Cuesheet")
        #self.button1.set_hexpand(True)
        self.button3.connect("clicked", self.on_cuesheet_split_button_clicked)

        self.box1_1_1.append(self.label1)
        self.box1_1_1.append(self.button1)
        self.box1_1_2.append(self.label2)
        self.box1_1_2.append(self.button2)
        self.box1_1.append(self.button3)

        self.frame1 = Gtk.Frame()
        self.frame1.set_label("Output Format Options")
        self.frame1.set_hexpand(True)
        self.frame1.set_vexpand(True) 
        self.frame1.set_margin_start(20)
        self.frame1.set_margin_end(20)
        self.box1_2.append(self.frame1)

        self.frame1_box1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.frame1_box1.set_margin_top(20)
        self.frame1_box1_1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=40)        
        self.frame1_box1_1.set_halign(Gtk.Align.CENTER)
        self.frame1_box1.append(self.frame1_box1_1)

        self.radio_button_ogg = Gtk.CheckButton(label="OGG")
        self.radio_button_mp3 = Gtk.CheckButton(label="MP3")
        self.radio_button_flac = Gtk.CheckButton(label="FLAC")
        self.radio_button_ogg.connect("toggled", self.update_dropdown1_options)
        self.radio_button_mp3.set_group(self.radio_button_ogg)
        self.radio_button_mp3.connect("toggled", self.update_dropdown1_options)
        self.radio_button_flac.set_group(self.radio_button_ogg)
        self.radio_button_flac.connect("toggled", self.update_dropdown1_options)
        self.radio_button_ogg.set_active(True)
        self.frame1_box1_1.append(self.radio_button_ogg)
        self.frame1_box1_1.append(self.radio_button_mp3)
        self.frame1_box1_1.append(self.radio_button_flac)
        self.frame1.set_child(self.frame1_box1)

        self.frame1_box1_2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        self.frame1_box1_2.set_halign(Gtk.Align.CENTER)
        self.frame1_box1_2.set_margin_bottom(20)
        self.frame1_box1.append(self.frame1_box1_2)
        self.label3 = Gtk.Label(label="Quality:")
        self.dropdown1_model = Gtk.StringList.new([])
        self.dropdown1 = Gtk.DropDown.new(self.dropdown1_model)
        self.update_dropdown1_options(self)
        self.frame1_box1_2.append(self.label3)
        self.frame1_box1_2.append(self.dropdown1)

        self.frame2 = Gtk.Frame()
        self.frame2.set_label("Batch Processing")
        self.frame2.set_hexpand(True)
        self.frame2.set_vexpand(True) 
        self.frame2.set_margin_start(20)
        self.frame2.set_margin_end(20)
        self.frame2.set_margin_bottom(20)
        self.box1_3.append(self.frame2)

        self.frame2_box1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self.frame2_box1.set_margin_top(20)
        self.frame2.set_child(self.frame2_box1)

        self.check_button_multiple_cuesheets = Gtk.CheckButton(label="Process Multiple Cuesheets")
        self.check_button_multiple_cuesheets.set_margin_start(20)
        self.frame2_box1.append(self.check_button_multiple_cuesheets)

        self.list_scrolled_window = Gtk.ScrolledWindow()
        self.list_scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.list_scrolled_window.set_margin_top(10)
        self.list_scrolled_window.set_margin_bottom(10)
        self.list_scrolled_window.set_margin_start(20)
        self.list_scrolled_window.set_margin_end(20)
        # Set the height of the scrolled window to approximately 4 rows
        self.list_scrolled_window.set_min_content_height(100)
        # Add the scrolled window to the frame1_box1 below other widgets
        self.frame2_box1.append(self.list_scrolled_window)
        # Create a ListBox to hold string labels
        self.list_box = Gtk.ListBox()
        self.list_scrolled_window.set_child(self.list_box)
        self.cuesheet_list = []
        self.check_button_multiple_cuesheets.connect("toggled", self.update_scrolled_list)
        

        # Setup drag and drop for the list box
        # Enable drag-and-drop of files onto the list box (GTK 4+)
        drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop_target.connect("drop", self.on_drop_files)
        self.list_box.add_controller(drop_target)

        self.frame2_box1_1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=40)        
        self.frame2_box1_1.set_halign(Gtk.Align.CENTER)
        self.frame2_box1.append(self.frame2_box1_1)
        self.frame2_box1_1.set_margin_start(20)
        self.frame2_box1_1.set_margin_end(20)
        self.frame2_box1_1.set_margin_bottom(20)
        self.button4 = Gtk.Button(label="Clear Selected Item")
        self.button4.set_hexpand(True)
        self.button4.connect("clicked", self.on_clear_selected_item_button_clicked)
        self.button5 = Gtk.Button(label="Clear All Items")
        self.button5.set_hexpand(True)
        self.button5.connect("clicked", self.on_clear_all_items_button_clicked)
        self.frame2_box1_1.append(self.button4)
        self.frame2_box1_1.append(self.button5)

        self.update_scrolled_list()

        # Status bar container at the bottom
        self.box_statusbar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=10
        )
        self.box_statusbar.set_margin_start(20)
        self.box_statusbar.set_margin_end(20)
        self.box_statusbar.set_margin_bottom(8)
        self.box_statusbar.set_margin_top(0)
        self.box_statusbar.add_css_class("statusbar")  # Adwaita friendly
        # Add a horizontal separator
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.add_css_class("separator")  # Ensures Adwaita-friendly style
        self.box1.append(separator)
        self.box1.append(self.box_statusbar)
        self.label_status = Gtk.Label(label="")
        self.label_status.set_xalign(0)  # Left-align
        self.label_status.set_valign(Gtk.Align.CENTER)
        self.label_status.set_margin_bottom(8)
        self.label_status.set_sensitive(False)
        self.box_statusbar.append(self.label_status)
        self.box_statusbar_spacer = Gtk.Box(hexpand=True)
        self.box_statusbar.append(self.box_statusbar_spacer)
        self.spinner = Gtk.Spinner()
        self.spinner.set_spinning(False)
        self.box_statusbar.append(self.spinner)


        # log file configuration & preparations
        scriptPath = os.path.split(os.path.realpath(__file__))[0]
        self.logFile = os.path.join(scriptPath, "cue-splitter.log")
        if __debug_mode__:
            self.logInit(logging.DEBUG)
        else:
            self.logInit(logging.INFO)
        self.log_message("*** App Cue-Splitter Started (PID: " + str(os.getpid()) + ") ***", "info")

        # process command line options
        if options.cuesheet_file and os.path.exists(options.cuesheet_file):
            self.button1.set_label(os.path.basename(options.cuesheet_file))
            self.button1.set_tooltip_text("Selected: " + options.cuesheet_file)
            self.cuesheet_list.append(options.cuesheet_file)
        if options.output_directory and os.path.exists(options.output_directory):
            self.button2.set_label(os.path.basename(options.output_directory))
            self.button2.set_tooltip_text("Selected: " + options.output_directory)


    ##
    ## Class Functions
    ##

    def create_cuesheet(self, cuesheet_file, originalPath):
        # factory method to allow inner class (Cuesheet) access methods from the outer class (MainWindow)
        # for next time: avoid nesting classes
        return MainWindow.Cuesheet(cuesheet_file, originalPath, self)

    def on_clear_all_items_button_clicked(self, button):
        self.cuesheet_list = []
        self.update_scrolled_list()

    def on_clear_selected_item_button_clicked(self, button):
        selected_row = self.list_box.get_selected_row()
        if selected_row is not None:
            idx = selected_row.get_index()
            if 0 <= idx < len(self.cuesheet_list):
                del self.cuesheet_list[idx]
                self.update_scrolled_list()

    def on_drop_files(self, drop_target, value, x, y):
        # value is a Gdk.FileList
        for gfile in value:
            path = gfile.get_path()
            if path and (path not in self.cuesheet_list):
                self.cuesheet_list.append(path)
        self.update_scrolled_list()
        return True  # Indicates drop was successful

    def update_scrolled_list(self, *args):
        self.list_box.remove_all()    
        if self.check_button_multiple_cuesheets.get_active():
            # Try to get the full path from the file selector tooltip (button1), if there is one
            single_path = self.button1.get_tooltip_text()
            if single_path and single_path.startswith("Selected: "):
                single_path = single_path[len("Selected: "):]  # Remove the prefix
                if single_path not in self.cuesheet_list:
                    self.cuesheet_list.insert(0, single_path)
        string_list = self.cuesheet_list
        if not string_list: 
            string_list = [" (Cuesheet List) "]

        for full_path in string_list:
            if full_path.startswith(" ("):  # For the placeholder texts
                display_text = full_path
                tooltip_text = None
            else:
                dirname = os.path.basename(os.path.dirname(full_path))
                filename = os.path.basename(full_path)
                display_text = f"{dirname}/{filename}"
                tooltip_text = full_path

            label = Gtk.Label(label=display_text, xalign=0)  # left aligned text
            if tooltip_text:
                label.set_tooltip_text(tooltip_text)

            row = Gtk.ListBoxRow()
            row.set_child(label)
            self.list_box.append(row)       
        self.list_scrolled_window.set_sensitive(self.check_button_multiple_cuesheets.get_active())
        # disable the Cuesheet file selection button if multiple cuesheets are selected
        self.button1.set_sensitive(not self.check_button_multiple_cuesheets.get_active())
        # enable or disable the list management buttons
        self.button4.set_sensitive(self.check_button_multiple_cuesheets.get_active())
        self.button5.set_sensitive(self.check_button_multiple_cuesheets.get_active())

    def update_dropdown1_options(self, selection=None):
        item_list = []
        default_value = None
        if not hasattr(self, "dropdown1"): return # if the object doesn't yet exist
        if self.radio_button_ogg.get_active():
            item_list = ["-1", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
            self.dropdown1.set_sensitive(True)
            default_value = "6"
        elif self.radio_button_mp3.get_active():
            item_list = [
                "b 320 (320 kbps)",
                "V 0 (245 kbps)",
                "V 1 (225 kbps)",
                "V 2 (190 kbps)",
                "V 3 (175 kbps)",
                "V 4 (165 kbps)",
                "V 5 (130 kbps)",
            ]
            self.dropdown1.set_sensitive(True)
            default_value = "V 1 (225 kbps)"
        else:
            # FLAC selected: disable the combo box
            item_list = []
            self.dropdown1.set_sensitive(False)
        # Set new model to dropdown
        self.dropdown1_model = Gtk.StringList.new(item_list)
        self.dropdown1.set_model(self.dropdown1_model)
        if self.dropdown1.get_sensitive() and default_value in item_list:
            index = item_list.index(default_value)
            self.dropdown1.set_selected(index)
        else: self.dropdown1.set_selected(0)

    def show_log_file(self, widget, data=None):
        # open the log file (if it exists) using the default text editor
        if os.path.isfile(self.logFile):
            subprocess.Popen(
                ("gnome-text-editor", self.logFile),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

    def logInit(self, loggingLevel):
        # Initialize the logging infrastructure (console and file)
        # Handles file rotation and maximum size (5 files, 1M each max)
        # Messages with level less than loggingLevel will not be recorded
        logging.basicConfig(
            level=loggingLevel, format="%(asctime)s - %(levelname)5s - %(message)s"
        )  # no file spec > logs to screen/stdout
        handler = logging.handlers.RotatingFileHandler(
            self.logFile, maxBytes=1000000, backupCount=5
        )
        formatter = logging.Formatter("%(asctime)s - %(levelname)5s - %(message)s")
        handler.setFormatter(formatter)
        logging.getLogger("").addHandler(handler)

    def log_message(self, message, msgType):
        # Logs the message to stdout using print, and to a file using
        # python's logging infrastructure
        if msgType == "debug" and __debug_mode__ == True:
            logging.debug(message)
        elif msgType == "info":
            logging.info(message)
        elif msgType == "warning":
            logging.warning(message)
        elif msgType == "error":
            logging.error(message)
        elif msgType == "critical":
            logging.critical(message)

    def adjust_widget_sensitivities(self, working_state):
        # adjusts the GUI widgets' sensitivities based on the
        # whether the application is working or not
        # working_stat: boolean

        self.label_status.set_sensitive(working_state)
        self.spinner.set_spinning(working_state)
        self.button1.set_sensitive(not working_state)
        self.button2.set_sensitive(not working_state)
        self.button3.set_sensitive(not working_state)
        self.frame1.set_sensitive(not working_state)
        self.hamburger.set_sensitive(not working_state)
        self.frame2.set_sensitive(not working_state)

    def on_output_folder_select_button_clicked(self, button):
        dialog = Gtk.FileDialog()
        initial_folder = Gio.File.new_for_path(options.output_directory)
        dialog.set_initial_folder(initial_folder)
        def on_folder_selected(dialog, result):
            try:
                file = dialog.select_folder_finish(result)  # Gio.File object or None
                if file:
                    folder_path = file.get_path()
                    if folder_path:
                        folder_name = os.path.basename(folder_path)
                        self.button2.set_label(folder_name)
                        self.button2.set_tooltip_text("Selected: " + folder_path)
            except Exception as e:
                pass

        dialog.select_folder(self, None, on_folder_selected)

    def on_cuesheet_select_button_clicked(self, button):
        dialog = Gtk.FileDialog()
        # Create a filter for '.cue' files
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Cuesheet files")
        file_filter.add_suffix("cue")  # Only allow .cue extension
        # Set the filter on the file dialog               
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(file_filter)
        dialog.set_default_filter(file_filter)
        dialog.set_filters(filters)
        def on_file_selected(dialog, result):
            try:
                file = dialog.open_finish(result)
                filepath = file.get_path()
                filename = os.path.basename(filepath) if filepath else None
                if filename:
                    self.button1.set_label(filename)
                    self.button1.set_tooltip_text("Selected: " + filepath)
                    self.cuesheet_list = []
                    self.cuesheet_list.append(filepath)
            except Exception as e:
                pass
        dialog.open(self, None, on_file_selected)

    def quit_app(self, action, param):
        self.close()

    def show_about(self, action, param):
        self.about = Gtk.AboutDialog()
        self.about.set_transient_for(self)
        self.about.set_modal(self)
        authors = [__author__ + " <" + __email__ + ">"]
        self.about.set_authors(authors)
        self.about.set_copyright(__copyright__)
        if __license__ == "GPLv3": licence = Gtk.License.GPL_3_0
        self.about.set_license_type(Gtk.License.GPL_3_0)
        self.about.set_website(__website__)
        self.about.set_website_label("Project Website")
        self.about.set_version(__version__)
        self.about.set_logo_icon_name(__app_icon_name__)
        self.about.set_comments(__comments__)
        self.about.show()

    def display_warning(self, messageText):
        dialog = Adw.MessageDialog.new(self, "Warning")
        dialog.set_body(messageText)
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.show()

    def convert_file_to_utf8(self, filename):
        # assumes that the file exists
        # uses the chardet library (installed by default in most distros)
        # to try to guess the current enconding (utf-8 vs. windows etc), and then re-encodes
        # if needed; detects en encoding hint set by flac-joiner
        with io.open(filename, "rb") as originalFile:
            rawdata = originalFile.read()
        if "-*- coding: utf-8 -*-" in str(rawdata):
            originalEncoding = "utf-8"
        else:
            originalEncoding = chardet.detect(rawdata)["encoding"]
        # encoding values include 'UTF-8', 'UTF-8-SIG' (with BOM, as produced by flac-joiner)
        # (if there was a BOM, then we need to strip it, hence saving as utf-8)
        if originalEncoding.lower() not in ["utf-8"]:
            with io.open(filename, "r", encoding=originalEncoding) as f:
                text = f.read()
            with io.open(filename, "w", encoding="utf8") as f:
                f.write(text)

    class Cuesheet:
            # Auxiliary class to parse and process cuesheets and audio image files

            def __init__(self, cuesheet_file, originalPath, cueSplitterInstance):
                self.originalPath = originalPath
                self.audioImage = False  # will hold an AudioImage object, if the image file exists
                self.cuesheet_file = cuesheet_file
                self.cueSplitterInstance = cueSplitterInstance
                self.parse_cuesheet(cuesheet_file)

            def remove_quotes_from_string(self, string):
                # if the string has surrounding quotes (") or ('), they will be removed
                if (string[0] == '"') or (string[0] == "'"):
                    string = string[1:-1]  # remove the quotes
                return string

            def parse_cuesheet(self, cuesheet_file):
                # parses a cuesheet file, extracting all basic album info (flac file, album name, date, etc)
                # assumes single-file (standard), if more than one FILE line is found, an error is issued
                # will also store the full-path version of the file and check its existance
                # Returns the results in a cuesheetContent list, and parseStatusOK ( True == OK, False == Error)
                # self.songList format:
                #       [SongNumber, songTitle, songPerformer]

                file = open(cuesheet_file, "r")
                try:
                    cuesheetContent = file.readlines()
                    file.close()
                except:
                    self.cueSplitterInstance.log_message(
                        "Cuesheet parsing error (couldn't read file); cuesheet processing job aborted",
                        "error",
                    )
                    self.cueSplitterInstance.display_warning(
                        "Cuesheet parsing error (couldn't read file); cuesheet processing job aborted"
                    )
                    self.parseStatusOK = False
                    return

                gotPerformer = False
                gotTitle = False
                gotFile = False
                self.parseStatusOK = True

                # initialize key cuesheet values
                self.genre = ""
                self.dateYear = ""
                self.performer = ""
                self.title = ""

                # first parse the basic info
                for line in cuesheetContent:
                    if line[0:9].lstrip() == "REM GENRE":
                        self.genre = self.remove_quotes_from_string(str(line[9:]).strip())
                    if line[0:8].lstrip() == "REM DATE":
                        self.dateYear = self.remove_quotes_from_string(str(line[8:]).strip())
                        # verify that date is a number, otherwise blank the field
                        if not str(self.dateYear).isdigit():
                            self.dateYear = ""
                    if line[0:9].lstrip() == "PERFORMER" and not gotPerformer:
                        self.performer = self.remove_quotes_from_string(str(line[9:]).strip())
                        gotPerformer = True
                    if line[0:5].lstrip() == "TITLE" and not gotTitle:
                        self.title = self.remove_quotes_from_string(str(line[5:]).strip())
                        # if present, remove extra "HDAudio" tag
                        # if cutting to ogg or MP3, since it doesn't apply to lossy compression
                        if "[HDAudio]" in self.title:
                            self.title = (self.title.replace("[HDAudio]", "")).strip()
                        gotTitle = True
                    if line[0:4].lstrip() == "FILE":
                        if not gotFile:
                            self.filenameWithoutPath = self.remove_quotes_from_string(
                                str(line[4:]).strip()
                            )
                            # look for a closing quote (the opening quote was removed alread), and remove
                            # the reminder text (e.g.: " WAV)
                            quoteStart = self.filenameWithoutPath.find('"')
                            if quoteStart:
                                self.filenameWithoutPath = (
                                    self.filenameWithoutPath[:quoteStart]
                                ).strip()
                            gotFile = True
                            self.audioImageFilename = os.path.join(
                                self.originalPath, self.filenameWithoutPath
                            )
                            if not os.path.isfile(self.audioImageFilename):
                                self.parseStatusOK = False  # the audio image does not exist
                            else:  # find out audio image details (bitrate etc)
                                self.audioImage = MainWindow.AudioImage(self.audioImageFilename)
                        else:
                            # invalid cuesheet: more than one FILE statement
                            self.parseStatusOK = False
                    if (line.strip())[0:5] == "TRACK":
                        # break out of the basic info parsing loop since we are now in the track section
                        break

                # now parse the songs/performers; look for each TRACK, then  TITLE/Performer
                # first parse the basic info
                currentSongNumber = 0
                songPerformer = ""
                songTitle = ""
                songIndex = ""
                self.songList = []
                for line in cuesheetContent:
                    if (line.strip())[0:5] == "TRACK":
                        # get the current song number
                        currentSongNumber = (line.strip())[6:8]
                    if line.strip()[0:9] == "PERFORMER" and currentSongNumber:
                        songPerformer = self.remove_quotes_from_string(str(line.strip()[9:]).strip())
                    if line.strip()[0:5] == "TITLE" and currentSongNumber:
                        songTitle = self.remove_quotes_from_string(str(line.strip()[5:]).strip())
                    if (line.strip())[0:5] == "INDEX" and currentSongNumber:
                        songIndex = self.remove_quotes_from_string(str(line.strip()[8:]).strip())
                    # once we captured track #, performer and title, add an entry to the song list
                    # and reset the trac/performer/title variables
                    if currentSongNumber and songPerformer and songTitle and songIndex:
                        self.songList.append([currentSongNumber, songTitle, songPerformer, songIndex])
                        currentSongNumber = 0
                        songTitle = ""
                        songPerformer = ""
                        songIndex = ""

                if not gotFile or not self.songList or currentSongNumber:
                    # no file statement detected, or no songs were found, or a song was half-processed
                    # this is an error condition
                    self.parseStatusOK = False
                return

    class AudioImage:
        # Auxiliary class to analyze and hold attributes of audio image files

        def __init__(self, audioImageFilename):
            self.audioImageFilename = audioImageFilename
            self.audioFileType = False
            self.bitsPerSample = False
            self.sampleRate = False
            self.analize_audio_image()

        def analize_audio_image(self):
            # if invoked, analyzes the audio file and determines its parameters
            # bitrate, bits per sample, etc

            # first probe for aiff
            try:
                info = mediainfo(self.audioImageFilename)
                self.audioFileType = info['format_name']
                self.sampleRate = info['sample_rate']
                self.bitsPerSample = info.get('bits_per_sample')
                self.audioFileType = self.audioFileType.upper()
            except Exception:
                # print("  AudioImage probing error (AIFF): " + str(e))
                pass

            if not self.audioFileType:
                try:
                    audioFileTag = FLAC(self.audioImageFilename)
                    self.bitsPerSample = audioFileTag.info.bits_per_sample
                    self.sampleRate = audioFileTag.info.sample_rate
                    self.audioFileType = "FLAC"
                except Exception:
                    # print("  AudioImage probing error (Flac/Mutagen): " + str(e))
                    pass
            if not self.audioFileType:
                try:
                    waveStream = wave.open(self.audioImageFilename, "rb")
                    self.sampleRate = waveStream.getframerate()
                    self.bitsPerSample = waveStream.getsampwidth() * 8
                    self.audioFileType = "WAVE"
                except Exception:
                    # print("  AudioImage probing error (Wave): " + str(e))
                    pass
            print(
                "[AudioImage File Type Probing: type:"
                + str(self.audioFileType)
                + " sampleRate:"
                + str(self.sampleRate)
                + " bitsPerSample:"
                + str(self.bitsPerSample)
                + "]"
            )


    def on_cuesheet_split_button_clicked(self, button):
        # splits the selected cuesheet - or the list of cuesheets, if applicable
        # by forking a process that runs ffmpeg
        # the splitting is done to a temp folder; then the tags are transferred, then the folder is renamed

        # determine the parameters for the splitting
        tooltip = self.button2.get_tooltip_text()
        if tooltip and tooltip.startswith("Selected: "):
            self.output_directory = tooltip[len("Selected: "):]
        else:
            self.output_directory = None  # or fallback to some default

        if self.radio_button_ogg.get_active():
            self.codec = "OGG"
        elif self.radio_button_mp3.get_active():
            self.codec = "MP3"
        elif self.radio_button_flac.get_active():
            self.codec = "FLAC"

        selected_index = self.dropdown1.get_selected()
        self.quality = None
        if selected_index >= 0:  # valid index
            self.quality = self.dropdown1_model.get_string(selected_index)

        self.log_message(
            "  Starting splitting process: output folder: " + str(self.output_directory), "info"
        )
        self.log_message("          codec: " + str(self.codec), "info")
        self.log_message("        quality: " + str(self.quality), "info")
        self.log_message("    concurrency: " + str(concurrency_limit), "info")

        if not self.cuesheet_list:
            self.log_message(
                "No valid cuesheet file/s were selected; cuesheet processing job aborted", "error"
            )
            self.display_warning(
                "No valid cuesheet file/s were selected; cuesheet processing job aborted"
            )
            return

        if not self.output_directory or not os.path.exists(self.output_directory):
            self.log_message(
                "The selected output directory ["
                + str(self.output_directory)
                + "] does not exist; cuesheet processing aborted",
                "error",
            )
            self.display_warning(
                "The selected output directory is not valid; cuesheet processing aborted"
            )
            return

        self.log_message("List of cuesheets to process: " + str(self.cuesheet_list), "info")
        successfullySplittedCuesheets = 0
        erroredSplittedCuesheets = 0
        
        cuesheetInProcess = 1

        for cuesheet_file in self.cuesheet_list:
            self.log_message(" Processing cuesheet: " + str(cuesheet_file), "info")
            self.label_status.set_text(
                "Processing Cuesheet: "
                + str(cuesheetInProcess).strip()
                + " of "
                + str(len(self.cuesheet_list)).strip()
                + " (splitting)"
            )
            # Logic:
            #  - copy the cuesheet to the temp folder, convert it to utf8,
            #  - parse the UTF8 version of the cuesheet for:
            #      > flac filename, album title, artist, date, genre
            #  - create a temporary dir; the variable content will include the name and full path
            tempDir = tempfile.mkdtemp(prefix="tmp", dir=self.output_directory)
            tempCue = os.path.join(tempDir, "CDImage.cue")
            shutil.copyfile(cuesheet_file, tempCue)
            self.convert_file_to_utf8(tempCue)

            # parse the cuesheet using my Cuesheet class
            cuesheetContent = self.create_cuesheet(tempCue, os.path.dirname(cuesheet_file))
            if not cuesheetContent.parseStatusOK:
                self.log_message(
                    "Aborting this cuesheet split due to parsing errors (check the cuesheet format), will continue with the next cuesheet if in batch mode",
                    "warning",
                )
                erroredSplittedCuesheets = erroredSplittedCuesheets + 1
                shutil.rmtree(tempDir)
                continue

            self.log_message("  Parsed Values: ", "info")
            self.log_message("          title: " + cuesheetContent.title, "info")
            self.log_message("      performer: " + cuesheetContent.performer, "info")
            self.log_message("           date: " + cuesheetContent.dateYear, "info")
            self.log_message("          genre: " + cuesheetContent.genre, "info")
            self.log_message("      audiofile: " + cuesheetContent.audioImageFilename, "info")
            self.log_message("       songList: " + str(cuesheetContent.songList), "info")
            self.log_message("       parse OK: " + str(cuesheetContent.parseStatusOK), "info")

            # Logic:
            #  - invoke the splitting tool via new thread, display spinner
            #  - clean the track filenames removing spaces, accents, and other unfriendly characters
            #  - transfer tags and art via function encapsulating cuetag and then manually transferring genre and year
            #  - delete the temporary cuesheet copy
            #  - run replaygain
            #  - rename the temp dir using artist - title

            self.adjust_widget_sensitivities(working_state=True)
            self.worker_processing = True
            self.splittingSucceeded = False
            workerArguments = [
                tempCue,
                cuesheetContent.audioImageFilename,
                self.codec,
                self.quality,
                len(cuesheetContent.songList),
                cuesheetContent,
            ]
            WT = WorkerThread(self.file_split_ffmpeg, workerArguments, self)            
            WT.start()
            # now wait until the thread finishes (otherwise we would open lots of threads)
            # but while waiting, allow gtk to update the UI, and activate spinner
            while self.worker_processing:
                #self.progressbarActivity.pulse()
                while GLib.MainContext.default().iteration(False):
                    pass
                time.sleep(0.02)
            self.log_message("  Completed track splitting", "info")

            # cleanup the track filenames
            self.cleanup_track_filenames(tempDir)
            self.log_message("  Completed track filename cleanup", "info")
            # transfer tags to tracks
            self.transfer_tags(tempCue, cuesheetContent)
            self.transfer_cover(os.path.dirname(cuesheet_file), tempDir)
            self.label_status.set_text(
                "Processing Cuesheet: "
                + str(cuesheetInProcess).strip()
                + " of "
                + str(len(self.cuesheet_list)).strip()
                + " (replay gain analysis)"
            )
            self.worker_processing = True
            WT = WorkerThread(self.process_replay_gain, tempDir, self)            
            WT.start()
            # now wait until the thread finishes (otherwise we would open lots of threads)
            # but while waiting, allow gtk to update the UI, and activate spinner
            while self.worker_processing:
                while GLib.MainContext.default().iteration(False):
                    pass
                time.sleep(0.02)            
            self.log_message("  Completed replay-gain analysis for all album tracks", "info")
            self.adjust_widget_sensitivities(working_state=False)

            # remove temporary cuesheet
            os.remove(tempCue)

            # rename the temp folder; do not create excessively long directory names
            newDirName = cuesheetContent.performer + " - " + cuesheetContent.title
            newDirName = newDirName.replace(":", "-")
            newDirName = newDirName.replace("/", "-")
            newDirName = newDirName.replace("\\", "-")
            newDirName = newDirName.replace("!", "")
            newDirName = newDirName.replace("?", "_")
            newDirName = newDirName.replace("*", "_")
            if len(newDirName) > 42:
                newDirName = newDirName[:42] + "_"
            newDirName = os.path.join(os.path.split(tempDir)[0], newDirName)
            # check if the new dir already exists and if so, rename secuentially
            if os.path.exists(newDirName):
                newDirName = newDirName + "_1"
                while os.path.exists(newDirName):
                    # get the number behind the last occurrence of "_"
                    seqNumber = int(newDirName[newDirName.rfind("_") + 1 :])
                    seqNumber += 1
                    newDirName = newDirName[: newDirName.rfind("_") + 1] + str(seqNumber)
            if not os.path.exists(newDirName):
                os.rename(tempDir, newDirName)
                self.log_message(
                    "  Successfully splitted the cuesheet, folder: " + newDirName, "info"
                )
            else:
                self.log_message(
                    "  Error: could not rename the temp directory ["
                    + tempDir
                    + "] due to final folder name already existing ["
                    + newDirName
                    + "] - please fix manually",
                    "error",
                )
                self.splittingSucceeded = False

            if not self.splittingSucceeded:
                self.log_message(
                    "  Error: splitting the cuesheet did not complete successfully", "error"
                )
                erroredSplittedCuesheets = erroredSplittedCuesheets + 1
                # raise SystemExit
                # shutil.rmtree(tempDir)
                continue
            else:
                successfullySplittedCuesheets = successfullySplittedCuesheets + 1

            cuesheetInProcess = cuesheetInProcess + 1

        statusMessage = "Cue-splitter job done ("
        if successfullySplittedCuesheets:
            statusMessage = statusMessage + str(successfullySplittedCuesheets) + " split/s OK, "
        if erroredSplittedCuesheets:
            statusMessage = (
                statusMessage + str(erroredSplittedCuesheets) + " split/s with errors - see log"
            )
        else:
            statusMessage = statusMessage + "no errors"
        statusMessage = statusMessage + ")"
        self.log_message(statusMessage, "info")
        self.label_status.set_text(statusMessage)

    def transfer_cover(self, sourceDir, destinationDir):
        # finds out if the source had a cover (cover.front.jpg) and
        # if so creates a 500x500px copy of it as cover.jpg in the output (splitted tracks) folder
        sourceCoverExists = False

        if os.path.exists(os.path.join(sourceDir, "cover.front.jpg")):
            sourceCoverPath = os.path.join(sourceDir, "cover.front.jpg")
            sourceCoverExists = True
        elif os.path.exists(os.path.join(sourceDir, "cover.jpg")):
            sourceCoverPath = os.path.join(sourceDir, "cover.jpg")
            sourceCoverExists = True

        if sourceCoverExists:
            # shutil.copy2(sourceCoverPath, os.path.join(destinationDir, "cover.jpg"))
            im = Image.open(sourceCoverPath)
            im.thumbnail((500, 500), Image.Resampling.LANCZOS)
            im.save(os.path.join(destinationDir, "cover.jpg"), "JPEG")
            self.log_message("  Source cover file copied to destination directory", "info")
        else:
            self.log_message("  Source cover file was not found", "info")

    def process_replay_gain(self, tempDir):
        # assumes that the directory contains one album
        # uses rsgain to calculate replay gain in multi-threaded mode, to the entire temp directory
        # will calculate both album and track gain and peak values, and embed the tags
        # in the vorbis/id3 header

        extensions = ["*.ogg", "*.mp3", "*.flac"]
        filenameList = [filename
                        for ext in extensions
                        for filename in glob.glob(os.path.join(tempDir, ext))]
        if len(filenameList) > 0:
            commandLine = "rsgain easy --multithread=" + str(concurrency_limit) + ' "' + tempDir + '"'
            self.log_message(
                "  Preparing for ReplayGain analysis and tagging - command line: " + commandLine,
                "info",
            )
            exitCode = os.system(commandLine)
            if exitCode != 0:
                self.splittingSucceeded = False
                self.log_message("  ReplayGain failed (rsgain threw errors)", "warning")
        else:
            self.log_message(
                "  ReplayGain analysis and tagging skipped - no ogg files found in output", "info"
            )

    def transfer_tags(self, tempCue, cuesheetContent):
        # Logic:
        #    parse the songs/performer names into a list (in parse_cuesheet)
        #    build a file list, exclude CDImage.cue; order it alphabetically
        #    use mutagen framework to tag songname/artist/album/year/genre of each song (using id3v2.3 in mp3s)
        #     note: convert strings from UTF8 to Latin-1

        # build a list of the songs to tag
        if self.codec == "OGG":
            trackFileWildcard = "*.ogg"
        elif self.codec == "MP3":
            trackFileWildcard = "*.mp3"
        elif self.codec == "FLAC":
            trackFileWildcard = "*.flac"

        filenameList = []
        for filename in glob.glob(os.path.join(os.path.split(tempCue)[0], trackFileWildcard)):
            filenameList.append(filename)

        filenameList.sort()
        taggingError = False
        currentSong = 0
        if self.codec == "OGG":
            for filename in filenameList:
                fileTag = OggVorbis(filename)
                fileTag["title"] = cuesheetContent.songList[currentSong][1]
                fileTag["artist"] = cuesheetContent.songList[currentSong][2]
                fileTag["performer"] = cuesheetContent.performer
                fileTag["album"] = cuesheetContent.title
                fileTag["genre"] = cuesheetContent.genre
                fileTag["date"] = cuesheetContent.dateYear
                fileTag["tracknumber"] = str(currentSong + 1)

                try:
                    fileTag.save()  # pylint: disable=no-value-for-parameter
                except:
                    taggingError = True

                currentSong = currentSong + 1
                # print "TAG: ", fileTag.pprint()

        if self.codec == "MP3":
            for filename in filenameList:
                fileTag = EasyID3(filename)
                fileTag["title"] = cuesheetContent.songList[currentSong][1]
                fileTag["artist"] = cuesheetContent.songList[currentSong][2]
                fileTag["composer"] = cuesheetContent.performer
                fileTag["album"] = cuesheetContent.title
                fileTag["genre"] = cuesheetContent.genre
                fileTag["date"] = cuesheetContent.dateYear
                fileTag["tracknumber"] = str(currentSong + 1)
                try:
                    fileTag.save(filename)
                except:
                    taggingError = True
                currentSong = currentSong + 1
                # print "TAG: ", fileTag.pprint()

        if self.codec == "FLAC":
            for filename in filenameList:
                fileTag = FLAC(filename)
                fileTag["title"] = cuesheetContent.songList[currentSong][1]
                fileTag["artist"] = cuesheetContent.songList[currentSong][2]
                fileTag["performer"] = cuesheetContent.performer
                fileTag["album"] = cuesheetContent.title
                fileTag["genre"] = cuesheetContent.genre
                fileTag["date"] = cuesheetContent.dateYear
                fileTag["tracknumber"] = str(currentSong + 1)
                try:
                    fileTag.save()
                except:
                    taggingError = True

                currentSong = currentSong + 1
                # print "TAG: ", fileTag.pprint()

        if taggingError:
            self.log_message("  Tag transfer ended with an error condition", "error")
        else:
            self.log_message("  Tag transfer succeeded", "info")

    def cleanup_track_filenames(self, folder):
        # replace blank spaces with underscores and accented characters with their un-accented versions in the mp3 filenames
        # reason: increase compatibility with mp3 players, and allow cuetag to work
        # will also remove the pregap files (rm *pregap*) which also hurt cuetag (and are not real tracks)

        # get a list of the filenames with no path, in unicode
        folder = str(folder)
        filenameList = os.listdir(folder)

        for filename in filenameList:
            # remove all accented characters
            newFilename = self.cleanup_string(filename)
            # rename the file
            os.rename(os.path.join(folder, filename), os.path.join(folder, newFilename))
            # # get rid of any pre-gap file that shnsplit may have produced
            if "pregap." in newFilename:
                os.remove(os.path.join(folder, newFilename))

    def cleanup_string(self, string):
        # remove all accented characters
        newString = "".join(
            c for c in unicodedata.normalize("NFD", string) if unicodedata.category(c) != "Mn"
        )

        # remove spaces and weird characters
        for position in range(len(newString)):
            char = newString[position]
            if (
                char == " "
                or char == "?"
                or char == "¿"
                or char == ":"
                or char == "°"
                or char == "@"
                or char == "&"
                or char == "%"
                or char == "$"
                or char == "#"
                or char == "|"
                or char == "¡"
                or char == ">"
                or char == "<"
                or char == "~"
                or char == "`"
                or char == '"'
                or char == "/"
                or char == "`"
                or char == "´"
                or char == "¨"
                or char == "\\"
                or char == "*"
            ):
                newString = newString.replace(char, "_")
        return newString

    def convert_temp_cuesheet_to_milliseconds(self, tempCueFile):
        # converts the tempCueFile cue-breakpoints from the standard format (MM:SS:ff = frames)
        # to milliseconds (MM:SS.nnnnnnnnnn) (10 decimals)
        # as required by ffmpeg for properly locating the PCM audio sample to cut and maintain PCM audio signature
        # If the cuesheet indexes are already in milliseconds, it will leave them unchanged

        # open the cuesheet and look for the INDEX tag
        # sample line:      INDEX 01 3:54:74
        with open(tempCueFile) as f:
            cueContent = f.readlines()

        for index, line in enumerate(cueContent):
            if "INDEX" in line:
                # convert to 'fraction of seconds' format
                # supports timestamps with 'frames' (MM:SS:FF) and timestamps with 'milliseconds' (MM:SS:nnn)
                prefix, separator, tail = line.rpartition(":")  # pylint: disable=unused-variable
                if not "." in tail:
                    if len(tail) == 3:
                        # the tail contains the number of frames (MM:SS:FF) (and a newline char)
                        frames = int(tail)
                        fractionSec = frames * (1.0 / 75) * 10000000000
                        # convert to high resolution fractional second
                        convertedLine = prefix + "." + "{:010.0f}".format(fractionSec) + "\n"
                    elif len(tail) == 4:
                        # assume the tail already contains milliseconds  (MM:SS:nnn)
                        convertedLine = prefix + "." + tail
                else:
                    # implies that the input is in MM:SS.nnnnnn... format (any number of digits)
                    # leave the index line untouched
                    convertedLine = line
                cueContent[index] = convertedLine

        # re-write the temporary cuesheet
        with open(tempCueFile, "w") as f:
            f.writelines(cueContent)
        # os.system('cp "' + tempCueFile + '" "' + tempCueFile + '.checkConversion"')

    def file_split_ffmpeg(self, workerArguments):
        # uses ffmpeg to cut and re-encode an audio image file based on a parsed cuesheet file
        # ffmpeg handles HD Audio files (24/ 48-96-192Khz) better
        # The resulting ogg/mp3 will be downsampled to 44.1Khz if necessary
        # (FLACs though are never downsampled and bit depth is kept)
        # Supports any number of songs (including single-song CDs); split accuracy validated
        # (at the PCM audio sample level comparing audion signatures with foobar-cut tracks)

        tempcuesheet_file = workerArguments[0]
        tempoutput_directory = os.path.split(tempcuesheet_file)[0]
        audioImageFilename = workerArguments[1]
        codec = workerArguments[2]
        quality = workerArguments[3]
        numberOfSongs = workerArguments[4]  # pylint: disable=unused-variable
        cuesheet = workerArguments[5]

        # Uses ffmpeg for the split
        #  indexes[j] = sprintf("%d:%02d:%06.3f", i[1]/60, i[1]%60, i[2]+i[3]/75)
        #   ffmpeg -nostdin -i "$file" -ss $start ${stop:+-to $stop} "$track $title".m4a

        # ffmpeg notes:
        #   -ss :: seek, takes input in "MM:SS.nnn" format (so: convert temp cuesheet to millisecond format)
        #          [HH:]MM:SS[.m...]
        #   -to :: position (output)   - alternative: -t duration (same format)
        #   -ac :: audio channels in output
        #   -ab 192000  :: target bitrate (for mp3)
        #   -qscale:a 6 :: target quality (6 == 192kbps; 0...10)

        # Samples of transcoding
        #   ffmpeg -i input.flac -f aiff -acodec pcm_s24be output.aiff
        #       :: aiff is like wav but supports tags; only supported with PCM big-endian
        #   ffmpeg -i CDImage.flac -f wav -acodec pcm_s24le output.wav
        #       :: wav is only supported with little-endian sample representation
        #   ffmpeg -i mon_fichier.flac -acodec libvorbis -ac 2 -qscale:a 6 mon_fichier.ogg
        #   ffmpeg -i mon_fichier.flac -acodec mp3 -ac 2 -qscale:a 1 mon_fichier.mp3
        #   ffprobe: to probe a media file and display codec and stream info

        self.convert_temp_cuesheet_to_milliseconds(tempcuesheet_file)
        # read the new cuesheet
        cuesheetMilliseconds = self.create_cuesheet(tempcuesheet_file, tempoutput_directory)
        self.splittingSucceeded = True

        def convert_index_to_seconds(indexString):
            # assumes the index in the cuesheet is already in millisecond format ('.nnn')
            minutes, seconds = indexString.split(":")
            resultingSeconds = int(minutes) * 60 + float(seconds)
            return "{:.10f}".format(resultingSeconds)  # SS.nnn

        #  splits the full-album flac with up to "concurrency_limit" subprocess.run instances instead of using 
        #  a single call to os.system(cmd)to split the whole thing
        #  keep count of how many threads are running and their state and as instances finish, launch new ones
        
        # generate a list with all the shell commands needed to cut each of the songs
        commandsList=[]
        for index, track in enumerate(cuesheetMilliseconds.songList):
            cmd = "ffmpeg -hide_banner -loglevel info -i " + '"' + audioImageFilename + '"'
            if codec == "OGG":
                cmd += " -acodec libvorbis -ac 2 -qscale:a " + str(quality)
            elif codec == "MP3":
                cmd += " -acodec mp3 -ac 2"
                if quality[0] != "b":
                    cmd += " -qscale:a " + str(quality[2])
                else:
                    cmd += " -b:a 320k"
            elif codec == "FLAC":
                cmd += " -acodec flac -ac 2 -compression_level 5"

            if cuesheet.audioImage.sampleRate != 44100 and codec != "FLAC":
                cmd += " -ar 44100"
            start = convert_index_to_seconds(track[3])  # this is the songIndex
            cmd += " -ss " + start
            if index < (len(cuesheetMilliseconds.songList) - 1):
                stop = convert_index_to_seconds(cuesheetMilliseconds.songList[index + 1][3])
                duration = "{:.10f}".format(float(stop) - float(start))
                print("\nTrack start: " + start + " || stop: " + stop + " || duration: " + duration)
                cmd += " -t " + duration
            trackName = "{:02}_".format(int(track[0])) + MainWindow.cleanup_string(self, track[1])
            cmd += ' "' + os.path.join(tempoutput_directory, trackName) + "." + codec.lower() + '"'

            commandsList.append(cmd)
        
        # now launch multiple threads (subprocesses) in parallel (up to "concurrency_limit") to cut the songs
        processes = (subprocess.Popen(cmd, shell=True) for cmd in commandsList)
        running_processes = list(itertools.islice(processes, concurrency_limit))  # start new processes
        while running_processes:
            for i, process in enumerate(running_processes):
                returnCode = process.poll() # returns None if the process is still running
                if returnCode is not None:  # the process has finished
                    if returnCode != 0: self.splittingSucceeded = False
                    running_processes[i] = next(processes, None)  # start new process
                    if running_processes[i] is None: # no new processes
                        del running_processes[i]
                        break


class WorkerThread(threading.Thread):
    # generic worker thread
    # forks a new process and executes a function in it
    # the 'function' to thread is passed as a constructor parameter

    def __init__(self, function, function_args, parent):
        threading.Thread.__init__(self)
        self.function = function
        self.function_args = function_args
        self.parent = parent

    def run(self):
        self.parent.worker_processing = True
        self.function(self.function_args)
        self.parent.worker_processing = False

    def stop(self):
        self = None



class MyApp(Adw.Application):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.connect('activate', self.on_activate)

    def on_activate(self, app):
        self.win = MainWindow(application=app)
        self.win.present()


    def do_command_line(self, command_line):
        # Called when the application is launched with command-line arguments
        global options
        args = command_line.get_arguments()[1:]  # Ignore argv[0], which is the program name
 
        # parse command line options
        parser = OptionParser(
            "usage: %prog [options] cuesheet_file", version=__title__ + " " + __version__
        )

        parser.add_option(
            "-d",
            "--output_directory",
            dest="output_directory",
            action="store",
            type="string",
            default=default_output_directory,
            help="write report to DIRECTORY",
            metavar="DIRECTORY",
        )

        parser.add_option(
            "-c",
            "--codec",
            action="store",
            dest="codec",
            default="ogg",
            help="specify the codec (output format) [ogg | mp3 | flac], [default: %default]",
        )

        parser.add_option(
            "-q",
            "--quality",
            action="store",
            dest="quality",
            default="6",
            help="specify the quality target for the encoder (ogg only), [default: %default]",
        )

        parser.add_option(
            "-g",
            "--display-gui",
            action="store_false",
            dest="gui",
            default=True,
            help="indicates whether to use a Graphical User Interface or not, [default: %default]",
        )

        (options, args) = parser.parse_args()

        if  not os.path.isdir(options.output_directory): 
            options.output_directory = os.path.expanduser('~')

        if len(args) >= 1:            
            if not os.path.isabs(args[0]):
                options.cuesheet_file = os.path.join(os.getcwd(), args[0])
            else:
                options.cuesheet_file = args[0]
        else:
            options.cuesheet_file = None

        if testing_mode:
            options.cuesheet_file = testing_cuesheet
            options.output_directory = testing_output_directory

        self.activate()  # Usually activates the default window
        return 0  # Exit code


if __name__ == "__main__":

    if concurrency_limit > (os.cpu_count() - 4):
        concurrency_limit = max(1, os.cpu_count() - 4)

    app = MyApp(
            application_id="ari.app.CueSplitter", 
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE
            )
    app.run(sys.argv)
