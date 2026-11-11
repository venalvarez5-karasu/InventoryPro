"use strict";

document.addEventListener("DOMContentLoaded", () => {

    const byId = id => document.getElementById(id);

    const root = byId("tc-page");

    if (!root) return;

    const form = byId("tc-checkout-form");
    const orderType = byId("tc-order-type");
    const addressId = byId("tc-address-id");

    const selectDialog = byId("tc-address-dialog");
    const addDialog = byId("tc-add-address-dialog");

    const addForm = byId("tc-add-address-form");

    const subtotal = Number(root.dataset.subtotal);
    const depositPercent = Number(root.dataset.percent);

    const serviceAreas = JSON.parse(
        byId("tc-service-areas").textContent
    );

    const peso = value => {

        return new Intl.NumberFormat("en-PH", {
            style: "currency",
            currency: "PHP",
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(value);

    };

    // CHECKOUT HELPERS

    function selectedMethod() {

        return document.querySelector(
            'input[name="tc-fulfillment"]:checked'
        )?.value || "delivery";

    }

    function selectedPayment() {

        return form.querySelector(
            'input[name="payment_method"]:checked'
        )?.value;

    }

    function selectedAddress() {

        return Array.from(
            selectDialog.querySelectorAll(
                'input[name="tc-selected-address"]'
            )
        ).find(radio => radio.value === addressId.value);

    }

    function setAddress(radio) {

        if (!radio) return;

        addressId.value = radio.value;

        byId("tc-recipient").textContent =
            radio.dataset.recipient;

        byId("tc-address-text").textContent =
            radio.dataset.address;

        byId("tc-address-summary").hidden = false;
        byId("tc-no-address").hidden = true;

        updateCheckout();

    }

    function updateCheckout() {

        const pickup = orderType.value === "pickup";

        byId("tc-delivery-fields").hidden = pickup;
        byId("tc-pickup-fields").hidden = !pickup;

        byId("tc-fee-row").hidden = pickup;
        byId("tc-deposit-row").hidden = !pickup;

        byId("tc-cod-option").hidden = pickup;

        const cod = form.querySelector(
            'input[name="payment_method"][value="cod"]'
        );

        const gcash = form.querySelector(
            'input[name="payment_method"][value="gcash"]'
        );

        if (pickup) {

            gcash.checked = true;
            cod.checked = false;

        }

        const pickupDate = byId("tc-pickup-date");
        const pickupTime = byId("tc-pickup-time");

        pickupDate.required = pickup;
        pickupTime.required = pickup;

        const address = selectedAddress();

        const fee = pickup
            ? 0
            : address
                ? Number(address.dataset.fee)
                : NaN;

        const total = subtotal + fee;

        const deposit = (
            Math.round(
                (subtotal * depositPercent / 100) * 100
            ) / 100
        );

        byId("tc-fee-preview").textContent =
            pickup
                ? peso(0)
                : Number.isFinite(fee)
                    ? peso(fee)
                    : "Choose an address";

        byId("tc-total-preview").textContent =
            Number.isFinite(total)
                ? peso(total)
                : "—";

        byId("tc-deposit").textContent =
            peso(deposit);

        byId("tc-balance").textContent =
            peso(subtotal - deposit);

        const payment = selectedPayment();

        if (pickup) {

            byId("tc-payment-note").textContent =
                "Pay the GCash downpayment using the " +
                "bakery's official payment instructions. " +
                "Submit your reference for verification.";

        } else if (payment === "gcash") {

            byId("tc-payment-note").textContent =
                "Pay the full amount using GCash. " +
                "Admin will verify your payment.";

        } else {

            byId("tc-payment-note").textContent =
                "Pay the full amount upon delivery.";

        }

        const submit = byId("tc-place-order");

        submit.textContent = pickup
            ? "Place Pickup Order"
            : payment === "gcash"
                ? "Place GCash Order"
                : "Place COD Order";

        submit.disabled = (
            !pickup && !address
        );

    }

    // FULFILLMENT METHOD

    document.querySelectorAll(
        'input[name="tc-fulfillment"]'
    ).forEach(radio => {

        radio.addEventListener("change", () => {

            orderType.value = selectedMethod();

            updateCheckout();

        });

    });

    form.querySelectorAll(
        'input[name="payment_method"]'
    ).forEach(radio => {

        radio.addEventListener(
            "change",
            updateCheckout
        );

    });

    byId("tc-continue").addEventListener(
        "click",
        () => {

            orderType.value = selectedMethod();

            byId("tc-method-step").hidden = true;
            byId("tc-details-step").hidden = false;

            updateCheckout();

        }
    );

    byId("tc-back").addEventListener(
        "click",
        () => {

            byId("tc-details-step").hidden = true;
            byId("tc-method-step").hidden = false;

        }
    );

    // OPEN SELECT ADDRESS MODAL

    function openSelectDialog() {

        const selected = selectedAddress();

        if (selected) {
            selected.checked = true;
        }

        if (addDialog.open) {
            addDialog.close();
        }

        if (!selectDialog.open) {
            selectDialog.showModal();
        }

    }

    function closeSelectDialog() {

        if (selectDialog.open) {
            selectDialog.close();
        }

    }

    byId("tc-change-address").addEventListener(
        "click",
        openSelectDialog
    );

    byId("tc-address-close").addEventListener(
        "click",
        closeSelectDialog
    );

    // USE SAVED ADDRESS

    byId("tc-address-confirm").addEventListener(
        "click",
        () => {

            const chosen = selectDialog.querySelector(
                'input[name="tc-selected-address"]:checked'
            );

            if (!chosen) return;

            setAddress(chosen);

            closeSelectDialog();

        }
    );

    // OPEN ADD ADDRESS MODAL

    function openAddDialog() {

        closeSelectDialog();

        const errorBox = byId("tc-address-error");

        errorBox.hidden = true;
        errorBox.textContent = "";

        addForm.reset();

        resetOptions(
            byId("tc-city"),
            "Select city"
        );

        resetOptions(
            byId("tc-barangay"),
            "Select barangay"
        );

        if (!addDialog.open) {
            addDialog.showModal();
        }

    }

    function closeAddDialog() {

        if (addDialog.open) {
            addDialog.close();
        }

    }

    byId("tc-open-add-address").addEventListener(
        "click",
        openAddDialog
    );

    byId("tc-add-address-close").addEventListener(
        "click",
        () => {

            closeAddDialog();
            openSelectDialog();

        }
    );

    byId("tc-add-address-back").addEventListener(
        "click",
        () => {

            closeAddDialog();
            openSelectDialog();

        }
    );

    // ADDRESS DROPDOWNS

    const province = byId("tc-province");
    const city = byId("tc-city");
    const barangay = byId("tc-barangay");

    function resetOptions(select, placeholder) {

        select.replaceChildren(
            new Option(placeholder, "")
        );

    }

    function addOption(select, name, value = name) {

        select.add(
            new Option(name, value)
        );

    }

    let selectedCityCode = "";
    let provinceRequestId = 0;
    let barangayRequestId = 0;

    province.addEventListener(
        "change",
        async () => {

            const requestId = ++provinceRequestId;
            ++barangayRequestId;

            resetOptions(
                city,
                "Loading cities..."
            );

            resetOptions(
                barangay,
                "Select barangay"
            );

            selectedCityCode = "";

            if (!province.value) {

                resetOptions(
                    city,
                    "Select city"
                );

                return;
            }

            const chosenProvince = province.value;

            try {

                const url = new URL(
                    "/auth/address-options",
                    location.origin
                );

                url.searchParams.set(
                    "province",
                    chosenProvince
                );

                url.searchParams.set(
                    "level",
                    "city"
                );

                const response = await fetch(
                    url,
                    {
                        credentials: "same-origin"
                    }
                );

                if (!response.ok) {

                    throw new Error(
                        "Unable to load cities."
                    );

                }

                const data = await response.json();

                if (
                    requestId !== provinceRequestId ||
                    province.value !== chosenProvince
                ) {
                    return;
                }

                resetOptions(
                    city,
                    "Select city"
                );

                const coveredCities = (
                    data.items || []
                ).filter(item => {

                    return serviceAreas.some(area => {

                        return (
                            area.province === chosenProvince
                            &&
                            area.city_municipality
                                .toLowerCase() ===
                            item.name.toLowerCase()
                        );

                    });

                });

                coveredCities.forEach(item => {

                    addOption(
                        city,
                        item.name
                    );

                    city.options[
                        city.options.length - 1
                    ].dataset.code = item.code;

                });

                if (!coveredCities.length) {

                    resetOptions(
                        city,
                        "No covered cities available"
                    );

                }

            } catch (error) {

                resetOptions(
                    city,
                    "Cities unavailable"
                );

                showAddressError(error.message);

            }

        }
    );

    city.addEventListener(
        "change",
        async () => {

            const requestId = ++barangayRequestId;

            resetOptions(
                barangay,
                "Loading barangays..."
            );

            selectedCityCode =
                city.selectedOptions[0]?.dataset.code || "";

            const code = selectedCityCode;

            if (!code) {

                resetOptions(
                    barangay,
                    "Select barangay"
                );

                return;
            }

            try {

                const url = new URL(
                    "/auth/address-options",
                    location.origin
                );

                url.searchParams.set(
                    "province",
                    province.value
                );

                url.searchParams.set(
                    "level",
                    "barangay"
                );

                url.searchParams.set(
                    "city_code",
                    code
                );

                const response = await fetch(
                    url,
                    {
                        credentials: "same-origin"
                    }
                );

                if (!response.ok) {

                    throw new Error(
                        "Unable to load barangays."
                    );

                }

                const data = await response.json();

                if (
                    requestId !== barangayRequestId ||
                    selectedCityCode !== code
                ) {
                    return;
                }

                resetOptions(
                    barangay,
                    "Select barangay"
                );

                (data.items || []).forEach(item => {

                    addOption(
                        barangay,
                        item.name
                    );

                });

            } catch (error) {

                resetOptions(
                    barangay,
                    "Barangays unavailable"
                );

                showAddressError(error.message);

            }

        }
    );

    // ADD ADDRESS VALIDATION MESSAGE

    function showAddressError(message) {

        const box = byId("tc-address-error");

        box.textContent = message;
        box.hidden = false;

    }

    // SAVE ADDRESS WITH AJAX

    addForm.addEventListener(
        "submit",
        async event => {

            event.preventDefault();

            const saveButton = byId(
                "tc-save-address"
            );

            const errorBox = byId(
                "tc-address-error"
            );

            errorBox.hidden = true;
            errorBox.textContent = "";

            if (!addForm.reportValidity()) {
                return;
            }

            saveButton.disabled = true;
            saveButton.textContent = "Saving Address...";

            const values = Object.fromEntries(
                new FormData(addForm).entries()
            );

            try {

                const response = await fetch(
                    "/cart/address",
                    {
                        method: "POST",
                        credentials: "same-origin",

                        headers: {
                            "Content-Type": "application/json",
                            "X-CSRFToken": values.csrf_token
                        },

                        body: JSON.stringify(values)
                    }
                );

                const result = await response.json();

                if (!response.ok) {

                    throw new Error(
                        result.error ||
                        "Could not save address."
                    );

                }

                // CREATE SAVED ADDRESS OPTION

                const label = document.createElement(
                    "label"
                );

                label.className =
                    "tc-option tc-saved-address";

                const radio = document.createElement(
                    "input"
                );

                radio.type = "radio";
                radio.name = "tc-selected-address";
                radio.value = String(result.id);

                radio.dataset.fee = String(result.fee);
                radio.dataset.recipient =
                    result.recipient;

                radio.dataset.address =
                    result.address;

                radio.checked = true;

                const span = document.createElement(
                    "span"
                );

                const strong = document.createElement(
                    "strong"
                );

                const small = document.createElement(
                    "small"
                );

                strong.textContent = result.recipient;
                small.textContent = result.address;

                span.append(
                    strong,
                    small
                );

                label.append(
                    radio,
                    span
                );

                const list = byId(
                    "tc-saved-addresses"
                );

                const emptyMessage = byId(
                    "tc-empty-address"
                );

                if (emptyMessage) {
                    emptyMessage.remove();
                }

                list.prepend(label);

                // AUTO SELECT NEW ADDRESS

                setAddress(radio);

                closeAddDialog();

                addForm.reset();

            } catch (error) {

                showAddressError(error.message);

            } finally {

                saveButton.disabled = false;
                saveButton.textContent =
                    "Save and Use Address";

            }

        }
    );

    // CHECKOUT SUBMISSION

    form.addEventListener(
        "submit",
        event => {

            if (
                orderType.value === "delivery" &&
                !selectedAddress()
            ) {

                event.preventDefault();

                openSelectDialog();

                return;

            }

            if (orderType.value === "pickup") {

                const dateInput = byId(
                    "tc-pickup-date"
                );

                const timeInput = byId(
                    "tc-pickup-time"
                );

                if (
                    !dateInput.value ||
                    !timeInput.value
                ) {

                    event.preventDefault();

                    byId("tc-pickup-fields")
                        .scrollIntoView({
                            behavior: "smooth",
                            block: "center"
                        });

                    return;

                }

            }

            if (form.dataset.submitting === "1") {

                event.preventDefault();
                return;

            }

            form.dataset.submitting = "1";

            const submitButton = byId(
                "tc-place-order"
            );

            submitButton.disabled = true;
            submitButton.textContent =
                "Placing Order...";

        }
    );

    updateCheckout();

});
