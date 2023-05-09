import os
from typing import Callable

from pytheus.metrics import Labels, Sample
from pytheus.registry import REGISTRY, Collector, Registry

LINE_SEPARATOR = os.linesep
LABEL_SEPARATOR = ","
PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
HELP_CHARACTERS_TO_ESCAPE = {
    "\\": "\\\\",  # \ -> \\
    "\n": "\\n",  # \n -> \n (escaped)
}
LABEL_CHARACTERS_TO_ESCAPE = {
    "\\": "\\\\",  # \ -> \\
    '"': '\\"',  # " -> \"
    "\n": "\\n",  # \n -> \n (escaped)
}


def generate_metrics(registry: Registry = REGISTRY) -> str:
    """
    Returns the metrics from the registry in prometheus text format
    """

    from pytheus.backends.redis import MultiProcessRedisBackend

    MultiProcessRedisBackend._initialize_pipeline()

    # collect samples that are not yet stored with the value
    samples_dict = {}
    # samples = []
    for collector in registry.collect():
        samples_list = []
        # samples_dict[collector.name] = samples_list
        samples_dict[collector] = samples_list
        # exhaust the generator for the side effect of building the pipeline
        for sample in collector.collect():
            samples_list.append(sample)

    pipeline_data = MultiProcessRedisBackend._execute_and_cleanup_pipeline()
    values = [0 if item is None else item for item in pipeline_data if item not in (True, False)]

    # assign correct values to the samples
    for samples in samples_dict.values():
        owned_values = values[: len(samples)]
        values = values[len(samples) :]

        for sample, value in zip(samples, owned_values):
            sample.value = value

    lines = (
        generate_from_collector(collector, registry.prefix, samples)
        for collector, samples in samples_dict.items()
    )
    # lines = (
    #     generate_from_collector(collector, registry.prefix) for collector in registry.collect()
    # )
    output = LINE_SEPARATOR.join(lines)
    output += "\n"
    return output


def _escape_value(value: str) -> str:
    for original, replacement in LABEL_CHARACTERS_TO_ESCAPE.items():
        value = value.replace(original, replacement)
    return value


def _escape_help(value: str) -> str:
    for original, replacement in HELP_CHARACTERS_TO_ESCAPE.items():
        value = value.replace(original, replacement)
    return value


def format_labels(labels: Labels | None) -> str:
    if not labels:
        return ""
    label_str = (f'{name}="{_escape_value(value)}"' for name, value in labels.items())
    return f"{{{LABEL_SEPARATOR.join(label_str)}}}"


def generate_from_collector(
    collector: Collector, prefix: str | None = None, samples: list[Sample] | None = None
) -> str:
    """
    Returns the metrics from a given collector in prometheus text format
    """
    metric_name = f"{prefix}_{collector.name}" if prefix else collector.name
    help_text = f"# HELP {metric_name} {_escape_help(collector.description)}"
    type_text = f"# TYPE {metric_name} {collector.type_}"
    output = [help_text, type_text]

    # iterate over samples if passed directly else fallback to the collect() method
    samples_list = samples if samples else collector.collect()

    for sample in samples_list:
        label_str = format_labels(sample.labels)
        metric = f"{metric_name}{sample.suffix}{label_str} {sample.value}"
        output.append(metric)
    return LINE_SEPARATOR.join(output)


def make_wsgi_app(registry: Registry = REGISTRY) -> Callable:
    """Create a WSGI app which serves the metrics from a registry."""

    def prometheus_app(environ, start_response):  # type: ignore
        status = "200 OK"
        if environ["PATH_INFO"] == "/favicon.ico":
            # Serve empty response for browsers
            headers = [("", "")]
            output = ""
        else:
            output = generate_metrics(registry)
            headers = [("Content-Type", PROMETHEUS_CONTENT_TYPE)]
        start_response(status, headers)
        return [output.encode()]

    return prometheus_app
