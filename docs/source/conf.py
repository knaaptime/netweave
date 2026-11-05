# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
import inspect
import os
import sys

from packaging.version import Version

import netweave  # noqa: E402

project = "netweave"
copyright = "2026-, Eli Knaap"  # noqa: A001
author = "Eli Knaap"

version = Version(netweave.__version__).public  # remove commit hash
release = version

language = "en"
html_title = project

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "myst_nb",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.linkcode",
    "sphinx.ext.mathjax",
    "sphinx.ext.napoleon",
    "sphinx_copybutton",
    "sphinx_immaterial",
]

myst_enable_extensions = [
    "amsmath",
    "colon_fence",
    "deflist",
    "dollarmath",
    "html_image",
]

master_doc = "index"

templates_path = [
    "_templates",
]
exclude_patterns = []

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable", None),
    "pandas": ("https://pandas.pydata.org/docs", None),
    "geopandas": ("https://geopandas.org/en/stable", None),
    "shapely": ("https://shapely.readthedocs.io/en/stable", None),
    "pyproj": ("https://pyproj4.github.io/pyproj/stable", None),
}

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

autosummary_generate = True
napoleon_google_docstring = False
napoleon_numpy_docstring = True
napoleon_use_param = True
napoleon_use_rtype = True
# Render "Attributes" as :ivar: fields on the class. Documenting undocumented members
# as well would list every dataclass field a second time, without a description.
napoleon_use_ivar = True
autodoc_default_options = {
    "members": True,
    "inherited-members": True,
    "exclude-members": "__init__",
}
autoclass_content = "class"
autodoc_typehints = "none"
suppress_warnings = ["ref.ref"]

html_theme = "sphinx_immaterial"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_theme_options = {
    "icon": {
        "repo": "fontawesome/brands/github",
        "edit": "material/file-code",
    },
    "site_url": "https://knaaptime.github.io/netweave",
    "repo_url": "https://github.com/knaaptime/netweave/",
    "edit_uri": "blob/main/docs/source",
    "repo_name": "knaaptime/netweave",
    "features": [
        "navigation.sections",
        "navigation.top",
        "search.share",
        "search.suggest",
        "toc.follow",
        "toc.sticky",
        "content.code.copy",
        "content.action.edit",
    ],
    "palette": [
        {
            "media": "(prefers-color-scheme)",
            "toggle": {
                "icon": "material/brightness-auto",
                "name": "Switch to light mode",
            },
        },
        {
            "media": "(prefers-color-scheme: light)",
            "scheme": "default",
            "primary": "indigo",
            "accent": "indigo",
            "toggle": {
                "icon": "material/lightbulb",
                "name": "Switch to dark mode",
            },
        },
        {
            "media": "(prefers-color-scheme: dark)",
            "scheme": "slate",
            "primary": "indigo",
            "accent": "indigo",
            "toggle": {
                "icon": "material/lightbulb-outline",
                "name": "Switch to system preference",
            },
        },
    ],
    "version_dropdown": True,
    "version_json": "https://knaaptime.github.io/netweave/versions.json",
}
nb_execution_mode = "force"
nb_execution_timeout = -1
nb_kernel_rgx_aliases = {".*": "python3"}
nb_merge_streams = True
nb_execution_raise_on_error = True
nb_execution_show_tb = True


def linkcode_resolve(domain, info):
    """Point the source links at the file and lines on GitHub."""

    def find_source():
        # Walk to the object, stopping at the last part that resolves: a dataclass
        # field has no class attribute, so it links to its class instead.
        obj = sys.modules[info["module"]]
        for part in info["fullname"].split("."):
            try:
                obj = getattr(obj, part)
            except AttributeError:
                break
        obj = inspect.unwrap(obj)
        if isinstance(obj, property):
            obj = obj.fget
        fn = inspect.getsourcefile(obj)
        fn = os.path.relpath(fn, start=os.path.dirname(netweave.__file__))
        source, lineno = inspect.getsourcelines(obj)
        return fn, lineno, lineno + len(source) - 1

    if domain != "py" or not info["module"]:
        return None
    try:
        filename = "netweave/%s#L%d-L%d" % find_source()  # noqa: UP031
    except Exception:
        filename = info["module"].replace(".", "/") + ".py"
    tag = "main" if "dev" in release else ("v" + release)
    return f"https://github.com/knaaptime/netweave/blob/{tag}/{filename}"
