"""train-on-push demo: train a model and register it to the MLflow registry.

Runs inside the Gitea Actions job (openml/ci-runner) on the openml network, so
mlflow/minio resolve by name. Kept dependency-light on purpose (mlflow+sklearn).
"""
import os
import mlflow
from sklearn.datasets import make_classification
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"))
mlflow.set_experiment("ci-train")

X, y = make_classification(n_samples=2000, n_features=20, n_informative=12,
                           n_classes=3, random_state=0)
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=0)

with mlflow.start_run():
    mlflow.sklearn.autolog(registered_model_name="ci-model")
    clf = RandomForestClassifier(n_estimators=100, random_state=0).fit(Xtr, ytr)
    acc = float(accuracy_score(yte, clf.predict(Xte)))
    mlflow.log_metric("test_accuracy", acc)
    print(f"registered 'ci-model' — test_accuracy={acc:.4f}")
