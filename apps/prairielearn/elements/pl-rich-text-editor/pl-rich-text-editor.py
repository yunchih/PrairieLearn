import base64
import hashlib
import os
from enum import Enum

import chevron
import lxml.html
import prairielearn as pl


class Counter(Enum):
    NONE = "none"
    CHARACTER = "character"
    WORD = "word"


class InputFormat(Enum):
    HTML = "html"
    MARKDOWN = "markdown"


QUILL_THEME_DEFAULT = "snow"
PLACEHOLDER_DEFAULT = "Your answer here"
ALLOW_BLANK_DEFAULT = False
SOURCE_FILE_NAME_DEFAULT = None
DIRECTORY_DEFAULT = "."
MARKDOWN_SHORTCUTS_DEFAULT = True
CLIPBOARD_ENABLED_DEFAULT = True


def get_answer_name(file_name: str) -> str:
    return "_rich_text_editor_{}".format(
        hashlib.sha1(file_name.encode("utf-8")).hexdigest()
    )


def element_inner_html(element: lxml.html.HtmlElement) -> str:
    return (element.text or "") + "".join([
        str(lxml.html.tostring(c), "utf-8") for c in element.iterchildren()
    ])


def prepare(element_html: str, data: pl.QuestionData) -> None:
    element = lxml.html.fragment_fromstring(element_html)
    required_attribs = ["file-name"]
    optional_attribs = [
        "quill-theme",
        "source-file-name",
        "directory",
        "placeholder",
        "allow-blank",
        "format",
        "markdown-shortcuts",
        "counter",
        "clipboard-enabled",
    ]
    pl.check_attribs(element, required_attribs, optional_attribs)
    source_file_name = pl.get_string_attrib(
        element, "source-file-name", SOURCE_FILE_NAME_DEFAULT
    )
    element_text = element_inner_html(element)

    file_name = pl.get_string_attrib(element, "file-name")
    if "_required_file_names" not in data["params"]:
        data["params"]["_required_file_names"] = []
    elif file_name in data["params"]["_required_file_names"]:
        raise RuntimeError(
            "There is more than one file editor with the same file name."
        )
    data["params"]["_required_file_names"].append(file_name)

    if (
        source_file_name is not None
        and element_text
        and not str(element_text).isspace()
    ):
        raise ValueError(
            'Existing text cannot be added inside rich-text element when "source-file-name" attribute is used.'
        )


def render(element_html: str, data: pl.QuestionData) -> str:
    element = lxml.html.fragment_fromstring(element_html)
    file_name = pl.get_string_attrib(element, "file-name", "")
    answer_name = get_answer_name(file_name)
    quill_theme = pl.get_string_attrib(element, "quill-theme", QUILL_THEME_DEFAULT)
    placeholder = pl.get_string_attrib(element, "placeholder", PLACEHOLDER_DEFAULT)
    uuid = pl.get_uuid()
    source_file_name = pl.get_string_attrib(
        element, "source-file-name", SOURCE_FILE_NAME_DEFAULT
    )
    directory = pl.get_string_attrib(element, "directory", DIRECTORY_DEFAULT)
    input_format = pl.get_enum_attrib(element, "format", InputFormat, InputFormat.HTML)
    markdown_shortcuts = pl.get_boolean_attrib(
        element, "markdown-shortcuts", MARKDOWN_SHORTCUTS_DEFAULT
    )
    counter = pl.get_enum_attrib(element, "counter", Counter, Counter.NONE)
    clipboard_enabled = pl.get_boolean_attrib(
        element, "clipboard-enabled", CLIPBOARD_ENABLED_DEFAULT
    )
    element_text = element_inner_html(element)

    if data["panel"] == "question" or data["panel"] == "submission":
        html_params = {
            "name": answer_name,
            "file_name": file_name,
            "quill_theme": quill_theme,
            "placeholder": placeholder,
            "editor_uuid": uuid,
            "question": data["panel"] == "question",
            "submission": data["panel"] == "submission",
            "read_only": (
                "true"
                if (data["panel"] == "submission" or not data["editable"])
                else "false"
            ),
            "format": input_format.value,
            "markdown_shortcuts": "true" if markdown_shortcuts else "false",
            "counter": counter.value,
            "counter_enabled": counter != Counter.NONE,
            "clipboard_enabled": clipboard_enabled,
        }

        submitted_files = data["submitted_answers"].get("_files", [])
        submitted_file = next(
            (f for f in submitted_files if f.get("name", None) == file_name), None
        )
        if submitted_file:
            html_params["current_file_contents"] = submitted_file.get("contents")
            # If the mimetype is provided, override the input format
            if submitted_file.get("mimetype"):
                html_params["format"] = (
                    "html"
                    if submitted_file.get("mimetype") == "text/html"
                    else "markdown"
                )
        else:
            if source_file_name is not None:
                if directory == "serverFilesCourse":
                    directory = data["options"]["server_files_course_path"]
                elif directory == "clientFilesCourse":
                    directory = data["options"]["client_files_course_path"]
                else:
                    directory = os.path.join(
                        data["options"]["question_path"], directory
                    )
                file_path = os.path.join(directory, source_file_name)
                with open(file_path) as f:
                    text_display = f.read()
            else:
                text_display = element_text

            html_params["current_file_contents"] = base64.b64encode(
                text_display.encode("UTF-8").strip()
            ).decode()

        html_params["question"] = data["panel"] == "question"
        with open("pl-rich-text-editor.mustache", encoding="utf-8") as f:
            html = chevron.render(f, html_params).strip()

    elif data["panel"] == "answer":
        html = ""
    else:
        raise ValueError("Invalid panel type: " + data["panel"])

    return html


def parse(element_html: str, data: pl.QuestionData) -> None:
    element = lxml.html.fragment_fromstring(element_html)
    allow_blank = pl.get_boolean_attrib(element, "allow-blank", ALLOW_BLANK_DEFAULT)
    file_name = pl.get_string_attrib(element, "file-name", "")
    answer_name = get_answer_name(file_name)

    # Get submitted answer or return parse_error if it does not exist
    file_contents = data["submitted_answers"].get(answer_name, None)
    if not file_contents and not allow_blank:
        pl.add_files_format_error(data, f"No submitted answer for {file_name}")
        return

    # We will store the files in the submitted_answer["_files"] key,
    # so delete the original submitted answer format to avoid
    # duplication
    del data["submitted_answers"][answer_name]
    # Mimetype is explicitly set to ensure that we can distinguish newer
    # submissions (stored as HTML) from submissions using the older version of
    # pl-rich-text-editor (potentially stored in Markdown)
    pl.add_submitted_file(data, file_name, file_contents, mimetype="text/html")
