'''thonny-py5mode frontend
interacts with py5mode backend (backend > py5_imported_mode_backend.py).'''

# 1. Built-in modules:
import site, webbrowser
from functools import cache

from os import path, environ as env
from pathlib import Path, PurePath

from importlib import machinery, util
from subprocess import Popen
from sysconfig import get_path

from tkinter import BooleanVar
from tkinter.messagebox import showwarning

from types import ModuleType
from typing import cast, NamedTuple, Optional

# 2. Third-party modules:
from jdk import _IS_WINDOWS, OS, OperatingSystem

from thonny import get_runner, running, token_utils
from thonny.common import BackendEvent, InputSubmission
from thonny.editors import Editor
from thonny.languages import tr
from thonny.running import Runner
from thonny.shell import BaseShellText
from thonny.ui_utils import select_sequence

# 3. Local plugin modules:
from .about_plugin import add_about_py5mode_command
from .install_jdk import install_jdk, WORKBENCH, StrPath

# Modified tkColorPicker (by j4321) to work with Thonny for MacOS:
# https://GitHub.com/tabreturn/thonny-py5mode-tkcolorpicker
# Now vendored on this very repo:
from .py5colorpicker.tkcolorpicker import modeless_colorpicker

class BackendEvt(BackendEvent, InputSubmission):
    '''Type hint only: combines `BackendEvent` + `InputSubmission` to indicate
    that the former has been instantiated with an additional `data: str` field.

    This class adds no behavior or structure beyond typing. It exists solely to
    help static analysis tools recognize that a `BackendEvent` instance includes
    both `BackendEvent` attributes and a `data` field of type string.'''

PY5_IMPORTED_MODE = 'run.py5_imported_mode'
PY5_LOCATION = 'run.py5_location'

_MOVE_EVENT_NAME = '__MOVE__ '
'''Internal event name prefix for move operations.'''

_EXTRACT_MOVE_COORDS = slice(len(_MOVE_EVENT_NAME), -1)
'''Slice object to extract coordinate data from move event strings.'''

_MENU = NamedTuple('Py5Menu', ( # Define all fields as type str
    ('TOGGLE_PY5', str),
    ('P5_THEME', str),
    ('COLOR_PICKER', str),
    ('PY5_REF', str),
    ('PY5_PDF', str),
    ('SKETCH_DIR', str) ))(*map(tr, ( # Immediately invoked instantiation
        'Toggle imported mode for py5',
        'Apply recommended py5 settings',
        'Color selector',
        'py5 online reference',
        'py5 online pdf cheatsheet',
        'Show current sketch folder') ))
'''
NamedTuple containing UI translated labels for plugin py5mode related features:

- TOGGLE_PY5: Label for toggling py5 mode.
- P5_THEME: Label for applying recommended py5 settings.
- COLOR_PICKER: Label for the color selector tool.
- PY5_REF: Label for accessing the py5 reference.
- PY5_PDF: Label for viewing the py5 quick reference PDF.
- SKETCH_DIR: Label for showing the sketch folder.'''

_KEY_COMBOS = NamedTuple('Py5KeySequence', ( # Define all fields as type str
    ('TOGGLE_PY5', str),
    ('SKETCH_DIR', str) ))(*map(lambda os_keys: select_sequence(*os_keys), (
        ('<Control-J>', '<Command-J>'),
        ('<Control-j>', '<Command-j>')) ))
'''
NamedTuple of os-specific keyboard shortcuts for some items on the py5mode menu:

- TOGGLE_PY5: Shortcut to toggle py5 imported mode (Ctrl/Cmd + Shift + J).
- SKETCH_DIR: Shortcut to show the sketch folder (Ctrl/Cmd + J).'''

_NO_FILE = cast( tuple[str, str], tuple(map(tr, (
    'Editor is empty!', 'Do you have any file open in the editor now?'))) )
'''Translated error message tuple for when no file is open in editor.'''

_NOT_SAVED = cast( tuple[str, str], tuple(map(tr, (
    'Inexisting file!', 'Have you saved this code anywhere yet?'))) )
'''Translated error message tuple for when file hasn't been saved.'''

_EXTS = 'py', 'py5', 'pyde'
'''Supported file extensions for py5 sketches.'''

_HTTP, _PY5_SITE, _REF = 'https://', 'py5Coding', '.org/reference/'
_WEB_REF = _HTTP + _PY5_SITE + _REF
'''Complete URL for the py5 online API reference.'''

_GIT_RAW = _HTTP + 'raw.GitHubUserContent.com/'
_REF_PDF = _PY5_SITE + '/thonny-py5mode/main/assets/py5_quick_reference.pdf'
_WEB_PDF = _GIT_RAW + _REF_PDF
'''Complete URL for the py5 quick reference PDF.'''

def open_web_ref(): webbrowser.open(_WEB_REF) # Online py5 API reference
def open_web_pdf(): webbrowser.open(_WEB_PDF) # Online py5 PDF cheatsheet

_is_color_selector_open = False
'''Flag to track whether the color selector window is currently open.'''

def load_plugin() -> None:
    '''Thonny's plugin callback.'''
    create_py5_menu()
    monkey_patchings()
    add_about_py5mode_command(50)
    patch_token_coloring()
    set_py5_imported_mode() # Check JDK if Thonny is opened w/ py5mode active


def create_py5_menu() -> None:
    '''Adds Py5-related commands to Thonny's menu system.'''
    WORKBENCH.set_default(PY5_IMPORTED_MODE, False)

    cmd = WORKBENCH.add_command

    cmd('toggle', 'py5', _MENU.TOGGLE_PY5, toggle_py5_imported_mode, group=10,
        default_sequence=_KEY_COMBOS.TOGGLE_PY5, flag_name=PY5_IMPORTED_MODE)

    cmd('apply_py5_theme', 'py5', _MENU.P5_THEME, apply_py5_config, group=20)

    cmd('color_selector', 'py5', _MENU.COLOR_PICKER, color_selector, group=25,
        default_sequence='<Alt-c>')

    cmd('py5_reference', 'py5', _MENU.PY5_REF, open_web_ref, group=30)

    cmd('py5_quick_reference', 'py5', _MENU.PY5_PDF, open_web_pdf, group=30)

    cmd('open_folder', 'py5', _MENU.SKETCH_DIR, show_sketch_folder, group=40,
        default_sequence=_KEY_COMBOS.SKETCH_DIR)


def monkey_patchings() -> None:
    '''Applies monkey patches to Thonny internals for custom behavior.'''

    # Replace `_handle_program_output()` method with a patched version!
    # It's a non-public API, so its handling may vary across Thonny versions:
    h_p_o = BaseShellText._handle_program_output
    setattr(BaseShellText, 'original_handle_program_output', h_p_o)
    BaseShellText._handle_program_output = patched_handle_program_output

    # Store Runner's original `execute_current()` method on its class; so it
    # can be monkey-patched later (e.g., when toggling py5mode):
    setattr(Runner, 'original_execute_current', Runner.execute_current)


def patched_handle_program_output(self: BaseShellText, msg: BackendEvt) -> None:
    '''Catch display window movement events and store their coordinate pair in
    the config file. Forward other event types to the original method.'''

    # If the message isn't a window move event, delegate to the original handler
    # for shell logging as usual:
    if not msg.data.startswith(_MOVE_EVENT_NAME):
        return getattr(self, 'original_handle_program_output')(msg)

    # Extract the coordinate pair from the received message representing
    # Processing canvas' last location, and convert it to the CSV format:
    py5_loc = msg.data[_EXTRACT_MOVE_COORDS].replace(' ', ',') # "x,y"

    # Next, save it to the [run] section of file "configuration.ini" as key
    # 'py5_location', to be later used to set Processing's canvas location:
    WORKBENCH.set_option(PY5_LOCATION, py5_loc)


def apply_py5_config() -> None:
    '''Apply recommended py5 theme, syntax and settings for Thonny.'''

    WORKBENCH.set_option('view.ui_theme', 'Kyanite UI')
    WORKBENCH.set_option('view.syntax_theme', 'Kyanite Syntax')

    WORKBENCH.set_option('view.highlight_current_line', True)
    WORKBENCH.set_option('view.locals_highlighting', True)

    WORKBENCH.set_option('assistance.open_assistant_on_errors', False)
    WORKBENCH.set_option('view.assistantview', False)
    WORKBENCH.hide_view('AssistantView')

    WORKBENCH.reload_themes()


def get_py5mode_toggle_state_variable() -> BooleanVar:
    '''Get the variable keeping py5mode's current toggle button state.'''
    return cast( BooleanVar, WORKBENCH.get_variable(PY5_IMPORTED_MODE) )


def toggle_py5_imported_mode() -> None:
    '''Toggle py5 imported mode settings.'''
    var = get_py5mode_toggle_state_variable()
    var.set(not var.get())  # Toggle state of the py5Mode variable
    set_py5_imported_mode() # Toggle Thonny's runner behavior for py5mode


def set_py5_imported_mode() -> None:
    '''Set imported mode variable in Thonny's "configuration.ini" file.'''

    if WORKBENCH.in_simple_mode():
        env['PY5_IMPORTED_MODE'] = 'auto'
        install_jdk() # Check JDK/JAVA_HOME when in simple mode
        return

    is_on = get_py5mode_toggle_state_variable().get()
    env['PY5_IMPORTED_MODE'] = str(is_on)

    if is_on: # Switch on/off py5 run button behavior
        Runner.execute_current = patched_execute_current
        install_jdk() # Check JDK/JAVA_HOME when toggling on, but not off

    # Restore the original method when py5mode is off:
    else: Runner.execute_current = getattr(Runner, 'original_execute_current')

    # Must restart backend for py5 autocompletion upon installing JDK.
    # This line disables py5 autocompletion in this instance:
    if (runner := get_runner()): runner.restart_backend(False)


@cache
def get_module_first_location(module_name='py5_tools') -> str:
    '''Get 1st found path for module. Return an empty string on fail.'''
    if not ( spec := util.find_spec(module_name) ): return ''
    return paths[0] if (paths := spec.submodule_search_locations) else ''


def patched_execute_current(self: Runner, command_name: str) -> None:
    '''Override run button behavior to execute the py5 imported mode script via
    "py5_tools/tools/run_sketch.py".'''

    _ = self; _ = command_name # Unused parameters

    current_file, current_editor = get_current_filename_and_editor()
    if not current_editor: return

    if not current_file:
        # Thonny must 'save as' any new files, before it can run them:
        Editor.save_file(current_editor)
        current_file = get_current_filename_and_editor()[0]

    if current_file.split('.')[-1] not in _EXTS: return

    # Save and run py5 imported mode:
    current_editor.save_file()

    user_packages = site.getusersitepackages()
    site_packages = site.getsitepackages()[0]
    plug_packages = get_module_first_location()

    run_sketch_locations = (
        Path(user_packages + '/py5_tools/tools/run_sketch.py'),
        Path(site_packages + '/py5_tools/tools/run_sketch.py'),
        Path(plug_packages + '/tools/run_sketch.py'),
        Path(get_path('purelib') + '/py5_tools/tools/run_sketch.py') )

    run_sketch = ''

    for location in run_sketch_locations:
        # If location matches py5_tools path, use it:
        if location.is_file(): run_sketch = str(location); break

    # Set switch so Sketch will report window location:
    py5_switches = '--py5_options external'

    # Retrieve last display window location coords from "configuration.ini":
    py5_loc = ','.join( map(str, WORKBENCH.get_option(PY5_LOCATION, ())) )

    # Add location switch to command line:
    if py5_loc: py5_switches += ' location=' + py5_loc

    # Run command to execute sketch:
    working_directory = path.dirname(current_file)
    cd_cmd_line = running.construct_cd_command(working_directory) + '\n'
    cmd_parts = ['%Run', run_sketch, current_file]
    exe_cmd_line = running.construct_cmd_line(cmd_parts) + ' '
    exe_cmd_line += py5_switches + '\n'
    running.get_shell().submit_magic_command(cd_cmd_line + exe_cmd_line)


def color_selector() -> None:
    '''Open tkinter color selector'''

    global _is_color_selector_open

    if not _is_color_selector_open: # If one is not already open...
        _is_color_selector_open = True
        modeless_colorpicker(title=_MENU.COLOR_PICKER, parent=WORKBENCH)
        _is_color_selector_open = False


def patch_token_coloring() -> None:
    '''Add py5 keywords to syntax highlighting.'''

    # Can't use `dir(py5)` b/c of JVM check; hence loading instead of importing:
    py5_ref_path = str( PurePath(get_module_first_location(), 'reference.py') )
    loader = machinery.SourceFileLoader('py5_tools_reference', py5_ref_path)
    module = ModuleType(loader.name)
    loader.exec_module(module)

    # Get list containing all py5/Processing public API keywords:
    py5_api: list[str] = getattr(module, 'PY5_ALL_STR')

    # Concatenate py5/Processing API to Thonny's builtin list:
    extended_builtin = token_utils._builtinlist + py5_api

    # Make the extended API tokens Thonny's new syntax highlighting:
    matches = cast( str, token_utils.matches_any('builtin', extended_builtin) )
    token_utils.BUILTIN = r'([^.\'"\\#]\b|^)' + matches + '\\b'


def get_current_filename_and_editor() -> tuple[str, Optional[Editor]]:
    '''Return a tuple containing current filename and the editor instance.'''

    # Check if the editor is empty/blank:
    if not ( editor := WORKBENCH.get_editor_notebook().get_current_editor() ):
        showwarning(*_NO_FILE, parent=WORKBENCH); return '', None

    # Check if the file isn't an "<untitled>" (yet-to-be-saved) file:
    if not ( filename := editor.get_filename() ):
        showwarning(*_NOT_SAVED, parent=WORKBENCH); return '', editor

    return filename, editor


def show_sketch_folder() -> None:
    '''Open the enclosing folder of the current sketch file.'''
    filename = get_current_filename_and_editor()[0]
    open_file_manager( path.dirname(filename) ) # Open the OS file manager


def open_file_manager(path_dir: StrPath) -> None:
    '''Open file manager for Windows/Mac/Linux.'''

    if _IS_WINDOWS: file_manager = 'explorer' # Windows
    elif OS is OperatingSystem.MAC: file_manager = 'open' # MacOS
    else: file_manager = 'xdg-open' # Linux/Unix

    Popen( (file_manager, path_dir) )
