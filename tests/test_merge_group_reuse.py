"""Reuse de PDF consolidado: solo con manifiesto COMPLETE del mismo grupo."""

from app.application.services.merge_group_validation import group_can_reuse_existing_pdf


def test_group_cannot_reuse_without_manifest():
    assert (
        group_can_reuse_existing_pdf(
            id_pago="P1",
            expected_creditos=("264",),
            prev_manifest=None,
        )
        is False
    )


def test_group_reuses_complete_manifest_same_credits():
    assert (
        group_can_reuse_existing_pdf(
            id_pago="P1",
            expected_creditos=("264",),
            prev_manifest={
                "incomplete_groups": [],
                "outputs": [
                    {
                        "id_pago": "P1",
                        "status": "COMPLETE",
                        "expected_creditos": ["264"],
                        "credit_items": [{"credito": "264"}],
                    }
                ],
            },
        )
        is True
    )


def test_group_cannot_reuse_when_credits_differ():
    assert (
        group_can_reuse_existing_pdf(
            id_pago="P1",
            expected_creditos=("264", "265"),
            prev_manifest={
                "outputs": [
                    {
                        "id_pago": "P1",
                        "status": "COMPLETE",
                        "expected_creditos": ["264"],
                        "credit_items": [{"credito": "264"}],
                    }
                ],
            },
        )
        is False
    )
