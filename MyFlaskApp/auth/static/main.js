
"use strict";

document.addEventListener("DOMContentLoaded", () => {

    // SHOW / HIDE PASSWORD

    document
        .querySelectorAll("[data-password-toggle]")
        .forEach((button) => {

            button.addEventListener("click", () => {
                const input = document.getElementById(
                    button.dataset.passwordToggle
                );

                if (!input) return;

                const showing = input.type === "password";

                input.type = showing ? "text" : "password";
                button.textContent = showing ? "Hide" : "Show";

                button.setAttribute(
                    "aria-label",
                    showing ? "Hide password" : "Show password"
                );
            });
        });

    // REGISTRATION ELEMENTS

    const form = document.getElementById("register-form");

    const emailInput = form?.querySelector("#email");
    const mobileInput = form?.querySelector("#mobile_number");
    const passwordInput = form?.querySelector("#password");
    const confirmInput = form?.querySelector("#confirm_password");

    const emailFeedback = document.getElementById("email-feedback");
    const mobileFeedback = document.getElementById("mobile-feedback");
    const passwordFeedback = document.getElementById("password-feedback");
    const confirmFeedback = document.getElementById("confirm-feedback");

    // LETTERS ONLY: NAME FIELDS

    document
        .querySelectorAll("[data-letters-only]")
        .forEach((input) => {

            input.addEventListener("input", () => {
                const max = input.maxLength > 0
                    ? input.maxLength
                    : 160;

                input.value = input.value
                    .replace(/[^\p{L} ]/gu, "")
                    .replace(/ {2,}/g, " ")
                    .replace(/^ +/, "")
                    .slice(0, max);
            });
        });

    // PHILIPPINE MOBILE NUMBER

    document
        .querySelectorAll("[data-ph-mobile]")
        .forEach((input) => {

            input.addEventListener("input", () => {
                input.value = input.value
                    .replace(/[^0-9]/g, "")
                    .slice(0, 11);

                if (form && input === mobileInput) {
                    scheduleCheck(
                        "mobile_number",
                        mobileInput,
                        mobileFeedback
                    );
                }
            });
        });

    // POSTAL CODE: 4 DIGITS

    document
        .querySelectorAll("[data-ph-postal]")
        .forEach((input) => {

            input.addEventListener("input", () => {
                input.value = input.value
                    .replace(/[^0-9]/g, "")
                    .slice(0, 4);
            });
        });

    // OTP: 6 DIGITS

    document
        .querySelectorAll("[data-otp]")
        .forEach((input) => {

            input.addEventListener("input", () => {
                input.value = input.value
                    .replace(/[^0-9]/g, "")
                    .slice(0, 6);
            });
        });

    // INPUT HIGHLIGHTING

    function paint(input, feedback, state, message) {
        if (!input || !feedback) return;

        input.classList.remove("is-valid", "is-invalid");

        if (state === "success") {
            input.classList.add("is-valid");
        }

        if (state === "error") {
            input.classList.add("is-invalid");
        }

        feedback.className = state
            ? "live-feedback " + state
            : "live-feedback";

        feedback.textContent = message || "";
    }

    // LIVE EMAIL / PHONE AVAILABILITY

    const timers = {};
    const controllers = {};

    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    const phonePattern = /^09[0-9]{9}$/;

    function scheduleCheck(field, input, feedback) {
        if (!form || !input || !feedback) return;

        clearTimeout(timers[field]);

        if (controllers[field]) {
            controllers[field].abort();
        }

        input.setCustomValidity("");

        const value = input.value.trim();

        if (!value) {
            paint(input, feedback, "", "");
            return;
        }

        const isEmail = field === "email";

        const valid = isEmail
            ? emailPattern.test(value) && value.length <= 190
            : phonePattern.test(value);

        if (!valid) {
            paint(
                input,
                feedback,
                "error",
                isEmail
                    ? "Enter a complete, valid email address."
                    : "Use exactly 11 digits starting with 09."
            );
            return;
        }

        paint(
            input,
            feedback,
            "checking",
            "Checking availability..."
        );

        timers[field] = setTimeout(async () => {
            const controller = new AbortController();
            controllers[field] = controller;

            try {
                const csrfToken = form.querySelector(
                    '[name="csrf_token"]'
                ).value;

                const response = await fetch(
                    form.dataset.checkUrl,
                    {
                        method: "POST",
                        credentials: "same-origin",
                        cache: "no-store",
                        headers: {
                            "Content-Type": "application/json",
                            "X-CSRFToken": csrfToken
                        },
                        body: JSON.stringify({
                            field: field,
                            value: value
                        }),
                        signal: controller.signal
                    }
                );

                if (!response.ok) {
                    throw new Error("Availability check failed");
                }

                const result = await response.json();

                // Ignore outdated responses
                if (
                    input.value.trim().toLowerCase() !==
                    value.toLowerCase()
                ) {
                    return;
                }

                if (result.exists) {
                    const message = isEmail
                        ? "This email is already registered."
                        : "This mobile number is already registered.";

                    input.setCustomValidity(message);

                    paint(
                        input,
                        feedback,
                        "error",
                        message
                    );
                } else {
                    input.setCustomValidity("");

                    paint(
                        input,
                        feedback,
                        "success",
                        isEmail
                            ? "Email is available."
                            : "Mobile number is available."
                    );
                }

            } catch (error) {
                if (error.name === "AbortError") {
                    return;
                }

                // The Python registration route will
                // still validate on submission.
                paint(
                    input,
                    feedback,
                    "checking",
                    "Unable to check right now. " +
                    "We'll check when you register."
                );

            } finally {
                if (controllers[field] === controller) {
                    delete controllers[field];
                }
            }
        }, 500);
    }

    // EMAIL INPUT LISTENER

    if (emailInput) {
        emailInput.addEventListener("input", () => {
            scheduleCheck(
                "email",
                emailInput,
                emailFeedback
            );
        });
    }

    // LIVE PASSWORD RULES

function updatePasswordRules() {
    if (!passwordInput) return;

    const password = passwordInput.value;

    const rules = {
        length: password.length >= 8 && password.length <= 128,
        symbol: /[^A-Za-z0-9\s]/.test(password),
        number: /[0-9]/.test(password)
    };

    const allPassed = Object.values(rules).every(Boolean);

    document
        .querySelectorAll("#password-rules [data-rule]")
        .forEach((item) => {
            const passed = rules[item.dataset.rule];

            item.classList.toggle("passed", passed);
            item.classList.toggle(
                "failed",
                password.length > 0 && !passed
            );
        });

    passwordInput.setCustomValidity(
        password.length > 0 && !allPassed
            ? "Password does not meet all requirements."
            : ""
    );

    if (!password.length) {
        paint(passwordInput, passwordFeedback, "", "");
    } else if (allPassed) {
        paint(
            passwordInput,
            passwordFeedback,
            "success",
            "Password meets all requirements."
        );
    } else {
        paint(
            passwordInput,
            passwordFeedback,
            "error",
            "Please complete the password requirements."
        );
    }

    updateConfirmPassword();
}

    // LIVE PASSWORD MATCHING

    function updateConfirmPassword() {
        if (!passwordInput || !confirmInput) return;

        const password = passwordInput.value;
        const confirmation = confirmInput.value;

        if (!confirmation) {
            confirmInput.setCustomValidity("");

            paint(
                confirmInput,
                confirmFeedback,
                "",
                ""
            );

            return;
        }

        if (password === confirmation) {
            confirmInput.setCustomValidity("");

            paint(
                confirmInput,
                confirmFeedback,
                "success",
                "Passwords match."
            );
        } else {
            confirmInput.setCustomValidity(
                "Passwords do not match."
            );

            paint(
                confirmInput,
                confirmFeedback,
                "error",
                "Passwords do not match."
            );
        }
    }

    if (passwordInput) {
        passwordInput.addEventListener(
            "input",
            updatePasswordRules
        );
    }

    if (confirmInput) {
        confirmInput.addEventListener(
            "input",
            updateConfirmPassword
        );
    }

    // VALIDATE BEFORE SUBMITTING

    if (form) {
        form.addEventListener("submit", (event) => {
            updatePasswordRules();
            updateConfirmPassword();

            if (emailInput) {
                const email = emailInput.value.trim();

                if (
                    email &&
                    !emailPattern.test(email)
                ) {
                    emailInput.setCustomValidity(
                        "Enter a valid email address."
                    );
                }
            }

            if (mobileInput) {
                const mobile = mobileInput.value.trim();

                if (
                    mobile &&
                    !phonePattern.test(mobile)
                ) {
                    mobileInput.setCustomValidity(
                        "Enter 11 digits starting with 09."
                    );
                }
            }

            if (!form.checkValidity()) {
                event.preventDefault();
                form.reportValidity();
                return;
            }

            const submit = form.querySelector(
                'button[type="submit"]'
            );

            if (submit) {
                submit.disabled = true;
                submit.textContent = "Creating account...";
            }
        });
    }

    // OTHER AUTH FORMS

    document
        .querySelectorAll(".auth-form:not(#register-form)")
        .forEach((otherForm) => {

            otherForm.addEventListener("submit", (event) => {
                if (!otherForm.checkValidity()) {
                    event.preventDefault();
                    otherForm.reportValidity();
                    return;
                }

                const submit = otherForm.querySelector(
                    'button[type="submit"]'
                );

                if (submit) {
                    submit.disabled = true;
                    submit.textContent = "Please wait...";
                }
            });
        });

});

// PHILIPPINE ADDRESS DROPDOWNS

document.addEventListener("DOMContentLoaded", () => {
    const province = document.getElementById("province");
    const city = document.getElementById("city_municipality");
    const barangay = document.getElementById("barangay");
    const status = document.getElementById("address-loading");

    if (!province || !city || !barangay) return;

    const endpoint = province.dataset.locationsUrl;

    let cityRequest = 0;
    let barangayRequest = 0;

    function resetSelect(select, message) {
        select.replaceChildren(new Option(message, ""));
        select.disabled = true;
    }

    function setStatus(message) {
        if (status) status.textContent = message;
    }

    async function getLocations(level, cityCode = "") {
        const url = new URL(endpoint, window.location.origin);

        url.searchParams.set("level", level);
        url.searchParams.set("province", province.value);

        if (cityCode) {
            url.searchParams.set("city_code", cityCode);
        }

        const response = await fetch(url, {
            credentials: "same-origin",
        });

        if (!response.ok) {
            throw new Error("Unable to load locations");
        }

        const data = await response.json();
        return data.items || [];
    }

    function fillSelect(select, items, placeholder) {
        resetSelect(select, placeholder);

        for (const item of items) {
            const option = new Option(item.name, item.name);
            option.dataset.code = item.code;
            select.add(option);
        }

        select.disabled = items.length === 0;
    }

    async function loadBarangays(preferred = "") {
        const requestId = ++barangayRequest;

        resetSelect(barangay, "Loading barangays...");

        if (!city.value) {
            resetSelect(barangay, "Select city first");
            setStatus("");
            return;
        }

        const selected = city.selectedOptions[0];
        const cityCode = selected?.dataset.code;

        if (!cityCode) return;

        setStatus("Loading barangays...");

        try {
            const items = await getLocations(
                "barangay",
                cityCode
            );

            if (requestId !== barangayRequest) return;

            fillSelect(
                barangay,
                items,
                "Select Barangay"
            );

            if (
                preferred &&
                [...barangay.options].some(
                    option => option.value === preferred
                )
            ) {
                barangay.value = preferred;
            }

            setStatus("");

        } catch (error) {
            if (requestId !== barangayRequest) return;

            resetSelect(
                barangay,
                "Unable to load barangays"
            );

            setStatus(
                "Could not load barangays. " +
                "Please try selecting the city again."
            );
        }
    }

    async function loadCities(
        preferredCity = "",
        preferredBarangay = ""
    ) {
        const requestId = ++cityRequest;
        ++barangayRequest;

        resetSelect(city, "Loading cities...");
        resetSelect(barangay, "Select city first");

        if (!province.value) {
            resetSelect(city, "Select province first");
            setStatus("");
            return;
        }

        setStatus("Loading cities and municipalities...");

        try {
            const items = await getLocations("city");

            if (requestId !== cityRequest) return;

            fillSelect(
                city,
                items,
                "Select City / Municipality"
            );

            if (
                preferredCity &&
                [...city.options].some(
                    option => option.value === preferredCity
                )
            ) {
                city.value = preferredCity;

                await loadBarangays(preferredBarangay);
            } else {
                setStatus("");
            }

        } catch (error) {
            if (requestId !== cityRequest) return;

            resetSelect(city, "Unable to load cities");

            setStatus(
                "Could not load cities. " +
                "Please select the province again."
            );
        }
    }

    province.addEventListener("change", () => {
        loadCities();
    });

    city.addEventListener("change", () => {
        loadBarangays();
    });

    // Restore saved address when editing a profile
    if (province.value) {
        loadCities(
            city.dataset.initial || "",
            barangay.dataset.initial || ""
        );
    }
});
