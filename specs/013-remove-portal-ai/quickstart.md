# Quickstart & Verification Guide: Removal of AI Prefill from Portal

**Feature Directory**: `specs/013-remove-portal-ai`  
**Date**: 2026-08-26  
**Status**: Complete

---

## 1. Automated Test Suite Execution

Run the complete test suite to verify that the portal and all supporting modules operate cleanly without AI dependencies.

```bash
# Run all unit tests
pytest tests/unit -v

# Run portal-specific tests
pytest tests/unit/test_ui_quality_checks.py tests/unit/test_assessor_completion.py tests/unit/test_portal_discrepancy.py tests/unit/test_joint_answers.py -v
```

---

## 2. End-to-End Portal Verification Workflow

### Step 1: Start the Portal Web Application
```bash
# Seed a clean test database with survey cycle and target portals
python src/portal/seed.py

# Launch the FastAPI web server
python src/cli.py serve --port 8000
```

---

### Step 2: Verify Assessor Workflow (Role A & B)
1. Open `http://localhost:8000/assessor/2026-test/portal_dk?role=A` in a browser.
2. **Visual Inspection**:
   - Verify NO AI suggestion boxes or bot alert banners appear.
   - Verify NO "Use AI Suggestion" buttons exist.
   - Verify indicator rubric (What / Why / How) is clearly readable.
3. Submit an indicator finding:
   - Select `Yes`, enter Evidence URL `https://borger.dk/health`, enter Notes `Verified official health portal service.`, and click **Save Finding**.
   - Verify page saves instantly and updates the "Your Current Submission" summary box.
4. Open the same unit as Assessor B: `http://localhost:8000/assessor/2026-test/portal_dk?role=B`.
   - Verify blindness is preserved (Assessor B does NOT see Assessor A's submission).
   - Enter an answer and submit.

---

### Step 3: Verify Admin Project Detail Page
1. Open `http://localhost:8000/admin/projects/2026-test`.
2. **Visual Inspection**:
   - Verify each unit card features a 2-column status layout (`Assessor Declarations` and `Assessor A/B Discrepancy`).
   - Verify NO "AI Assessment Run" status card appears.
   - Verify NO "Trigger AI Assessment" button is present in the actions toolbar.
   - Verify MSQ upload works without throwing candidate extraction errors.

---

### Step 4: Verify Human Discrepancy Reconciliation (Spec 012)
1. Complete all indicators on a test unit with differing answers between Assessor A and B above the project tolerance.
2. Declare completion for Role A and Role B.
3. Verify that the unit flags and redirects to the **Reconciliation Workspace** (`/assessor/2026-test/portal_dk/reconcile`).
4. Settle joint answers, observe the discrepancy badge turn green, and verify the Senior Reviewer can publish the finalized scorecard.
