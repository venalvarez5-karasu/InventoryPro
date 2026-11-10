
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const settings = document.getElementById(
        "adm-delivery-fee-settings"
    );

    if (!settings) return;

    const baseRaw = settings.dataset.baseFee;
    const rateRaw = settings.dataset.ratePerKm;

    const configured =
        baseRaw !== "" &&
        rateRaw !== "";

    const base = Number(baseRaw);
    const rate = Number(rateRaw);

    const currency = new Intl.NumberFormat("en-PH", {
        style: "currency",
        currency: "PHP",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });

    function updatePreview(form) {
        if (!form || !form.matches(
            "[data-delivery-area-form]"
        )) return;

        const distanceInput = form.querySelector(
            '[name="estimated_distance_km"]'
        );

        const preview = form.querySelector(
            "[data-delivery-fee-value]"
        );

        if (!distanceInput || !preview) return;

        const text = distanceInput.value.trim();

        if (!configured) {
            preview.textContent =
                "Configure delivery pricing first";
            return;
        }

        if (text === "") {
            const existing = form.dataset.existingFee;

            preview.textContent = existing
                ? "Existing manual fee: " +
                  currency.format(Number(existing))
                : "Enter an estimated distance";

            return;
        }

        const distance = Number(text);

        if (
            !Number.isFinite(distance) ||
            distance < 0 ||
            distance > 99999.99 ||
            !Number.isFinite(base) ||
            !Number.isFinite(rate)
        ) {
            preview.textContent = "Invalid distance";
            return;
        }

        const fee = base + (distance * rate);

        if (
            !Number.isFinite(fee) ||
            fee < 0 ||
            fee > 99999999.99
        ) {
            preview.textContent =
                "Fee exceeds the allowed amount";
            return;
        }

        // Preview only. Flask recalculates on save.
        preview.textContent = currency.format(
            Math.round((fee + Number.EPSILON) * 100) / 100
        );
    }

    // Delegated event handlers also work for forms
    // cloned into the Admin modal.

    document.addEventListener("input", (event) => {
        if (
            event.target.matches(
                '[data-delivery-area-form] ' +
                '[name="estimated_distance_km"]'
            )
        ) {
            updatePreview(
                event.target.closest(
                    "[data-delivery-area-form]"
                )
            );
        }
    });

    document.addEventListener("change", (event) => {
        if (
            event.target.matches(
                '[data-delivery-area-form] ' +
                '[name="estimated_distance_km"]'
            )
        ) {
            updatePreview(
                event.target.closest(
                    "[data-delivery-area-form]"
                )
            );
        }
    });

    // Render previews for existing page forms.
    document.querySelectorAll(
        "[data-delivery-area-form]"
    ).forEach(updatePreview);
});
