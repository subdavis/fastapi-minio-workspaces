import json
from json.decoder import JSONDecodeError
import click

from requests import Response


def handle_request_error(r: Response) -> dict:
    if not r.ok:
        # TODO: inspect content-type to infer this
        error_text = r.text
        try:
            error_text = r.json()
        except ValueError:
            pass

        headers = dict(r.request.headers)
        headers.pop("Authorization", None)
        body = str(r.request.body)
        try:
            body = json.loads(body)
        except JSONDecodeError:
            pass

        return {
            "context": {
                "url": r.url,
                "method": r.request.method,
                "status": r.status_code,
                "body": body,
                "headers": headers,
            },
            "error": error_text,
        }
    return {"response": r.json()}


def exit_with(out: dict):
    click.echo(json.dumps(out, indent=2, sort_keys=True))
    if out.get("error"):
        exit(1)
    exit(0)