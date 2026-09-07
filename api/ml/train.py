"""Train the churn classifier.

Two ensembles are fitted and compared with stratified cross-validation: a Random
Forest (bagging; stable with defaults) and XGBoost (sequential boosting; usually
higher accuracy on tabular data). The better one on held-out ROC-AUC is saved.

    python -m api.ml.train --wallets 6000 --out api/ml/models/churn.joblib
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from .features import FEATURE_NAMES, engineer_all
from .raw import MockCollector

MODEL_PATH = Path(__file__).resolve().parent / "models" / "churn.joblib"


def build_dataset(n_wallets: int, seed_mints: int = 12) -> tuple[np.ndarray, np.ndarray]:
    """Synthetic training set: many mock populations so archetype mixes vary."""
    col = MockCollector()
    now = int(time.time())
    X, y = [], []
    for i in range(seed_mints):
        for f in engineer_all(col.population(f"train-mint-{i}", n_wallets // seed_mints, now), now):
            X.append(f.vector())
            y.append(1 if f.label else 0)
    return np.asarray(X, dtype=float), np.asarray(y, dtype=int)


def candidates() -> dict[str, object]:
    models: dict[str, object] = {
        "random_forest": RandomForestClassifier(n_estimators=300, min_samples_leaf=3, n_jobs=-1, random_state=7),
    }
    try:
        from xgboost import XGBClassifier
        models["xgboost"] = XGBClassifier(
            n_estimators=400, learning_rate=0.05, max_depth=4, subsample=0.8, colsample_bytree=0.8,
            eval_metric="logloss", random_state=7, n_jobs=4,
        )
    except ImportError:
        pass
    return models


def train(X: np.ndarray, y: np.ndarray) -> tuple[str, object, dict[str, float]]:
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=7)
    scores: dict[str, float] = {}
    fitted: dict[str, object] = {}
    for name, model in candidates().items():
        proba = cross_val_predict(model, X, y, cv=cv, method="predict_proba")[:, 1]
        scores[name] = float(roc_auc_score(y, proba))
        fitted[name] = model.fit(X, y)
    best = max(scores, key=scores.get)
    return best, fitted[best], scores


def save(model: object, name: str, scores: dict[str, float], path: Path = MODEL_PATH) -> None:
    import joblib
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "name": name, "features": FEATURE_NAMES, "cv_auc": scores, "trained_at": int(time.time())}, path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallets", type=int, default=6000)
    ap.add_argument("--out", type=Path, default=MODEL_PATH)
    args = ap.parse_args()
    X, y = build_dataset(args.wallets)
    name, model, scores = train(X, y)
    save(model, name, scores, args.out)
    importances = getattr(model, "feature_importances_", None)
    print(json.dumps({
        "selected": name, "cv_auc": scores, "n": int(len(y)), "positive_rate": float(y.mean()),
        "feature_importance": dict(zip(FEATURE_NAMES, map(float, importances))) if importances is not None else None,
        "saved_to": str(args.out),
    }, indent=2))


if __name__ == "__main__":
    main()
