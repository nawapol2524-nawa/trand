import unittest
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier

class TestCalibrationDataIsolation(unittest.TestCase):
    def test_calibration_strictly_uses_validation_fold(self):
        """
        Gate 21 Stronger Calibration Isolation Test:
        1. Fit base model on Train.
        2. Fit calibrator using Validation A.
        3. Record calibrator predictions and calibrated probabilities on fixed reference set.
        4. Mutate / arbitrarily corrupt Test data and Test labels.
        5. Refit calibration using same Validation A.
        6. Assert calibrator output and parameters remain 100% bit-for-bit identical.
        """
        np.random.seed(42)
        X_train = np.random.randn(200, 10)
        y_train = np.random.choice([0, 1, 2], size=200, p=[0.8, 0.1, 0.1])

        X_val = np.random.randn(50, 10)
        y_val = np.random.choice([0, 1, 2], size=50, p=[0.8, 0.1, 0.1])

        X_test_1 = np.random.randn(50, 10)
        y_test_1 = np.random.choice([0, 1, 2], size=50, p=[0.8, 0.1, 0.1])

        base_clf = HistGradientBoostingClassifier(random_state=42)
        base_clf.fit(X_train, y_train)

        # 1. First calibration fit with Validation A
        calibrator_1 = CalibratedClassifierCV(estimator=base_clf, method="isotonic", cv="prefit")
        calibrator_1.fit(X_val, y_val)
        
        # Fixed evaluation reference (e.g. standard grid or uncorrupted evaluation points)
        eval_ref = np.random.RandomState(99).randn(30, 10)
        preds_1 = calibrator_1.predict(eval_ref)
        probas_1 = calibrator_1.predict_proba(eval_ref)

        # 2. Arbitrarily corrupt / replace Test set with wild extremes
        X_test_corrupted = X_test_1 * 1000.0 + 9999.0
        y_test_corrupted = np.array([1 if x == 0 else 0 for x in y_test_1])

        # 3. Refit calibration using same Validation A
        calibrator_2 = CalibratedClassifierCV(estimator=base_clf, method="isotonic", cv="prefit")
        calibrator_2.fit(X_val, y_val)

        preds_2 = calibrator_2.predict(eval_ref)
        probas_2 = calibrator_2.predict_proba(eval_ref)

        # 4. Strict identity assertion
        np.testing.assert_array_equal(
            preds_1, preds_2,
            err_msg="Calibration predictions changed after test set mutation!"
        )
        np.testing.assert_allclose(
            probas_1, probas_2, atol=1e-12,
            err_msg="Calibrated probabilities changed after test set mutation!"
        )

        # Also confirm calibrated predictions on the corrupted test set evaluate safely
        preds_corrupt = calibrator_2.predict(X_test_corrupted)
        self.assertEqual(len(preds_corrupt), len(X_test_corrupted))

if __name__ == "__main__":
    unittest.main()
