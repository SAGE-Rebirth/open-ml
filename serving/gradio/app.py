"""OpenML — Model Playground.

A small Gradio UI that calls the serving API (BentoML/FastAPI) and shows the
predicted iris species for a set of four flower measurements.
"""

import os

import gradio as gr
import requests

INFERENCE_URL = os.environ.get("INFERENCE_URL", "http://inference:8000")
PLAYGROUND_PORT = int(os.environ.get("PLAYGROUND_PORT", "7860"))

BLURB = f"""
# OpenML — Model Playground

Enter four iris flower measurements and click **Predict**. The app sends them to
the serving endpoint at `{INFERENCE_URL}/predict` and displays the model's
predicted species.
"""


def predict(sepal_length, sepal_width, petal_length, petal_width):
    """POST the four features to the serving API and return a readable result."""
    payload = {
        "inputs": [[sepal_length, sepal_width, petal_length, petal_width]]
    }
    try:
        response = requests.post(
            f"{INFERENCE_URL}/predict", json=payload, timeout=30
        )
        response.raise_for_status()
        data = response.json()
        label = data["labels"][0]
        index = data["predictions"][0]
        return f"Predicted species: {label} (class index {index})"
    except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
        return f"Error calling serving endpoint: {exc}"


with gr.Blocks(title="OpenML — Model Playground") as demo:
    gr.Markdown(BLURB)

    with gr.Row():
        sepal_length = gr.Number(
            label="Sepal length (cm)", value=5.1, minimum=0.0, maximum=10.0
        )
        sepal_width = gr.Number(
            label="Sepal width (cm)", value=3.5, minimum=0.0, maximum=10.0
        )
        petal_length = gr.Number(
            label="Petal length (cm)", value=1.4, minimum=0.0, maximum=10.0
        )
        petal_width = gr.Number(
            label="Petal width (cm)", value=0.2, minimum=0.0, maximum=10.0
        )

    predict_button = gr.Button("Predict", variant="primary")
    output = gr.Textbox(label="Result", interactive=False)

    predict_button.click(
        fn=predict,
        inputs=[sepal_length, sepal_width, petal_length, petal_width],
        outputs=output,
    )


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=PLAYGROUND_PORT)
