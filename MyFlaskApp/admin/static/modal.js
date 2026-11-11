
"use strict";

document.addEventListener("DOMContentLoaded", () => {

    const dialog = document.getElementById("adm-edit-dialog");
    const title = document.getElementById("adm-edit-title");
    const subtitle = document.getElementById("adm-edit-subtitle");
    const content = document.getElementById("adm-edit-content");
    const errorBox = document.getElementById("adm-edit-error");

    if (
        !dialog ||
        !title ||
        !subtitle ||
        !content ||
        !errorBox ||
        typeof dialog.showModal !== "function"
    ) {
        console.error(
            "Admin modal elements are missing or unsupported."
        );
        return;
    }

    const CLOSE_SELECTOR =
        "[data-adm-edit-close], [data-modal-close]";

    let opener = null;
    let saving = false;
    let loadingController = null;
    let previewURL = null;

    // ==========================================
    // HELPERS
    // ==========================================

    function actionURL(form) {
        return new URL(
            form.getAttribute("action") || location.href,
            location.href
        );
    }

    function setError(message) {
        errorBox.textContent = message;
        errorBox.hidden = !message;
    }

    function clearPreview() {
        if (previewURL) {
            URL.revokeObjectURL(previewURL);
        }

        previewURL = null;
    }

    function cancelButton() {
        const button = document.createElement("button");

        button.type = "button";
        button.className = "adm-secondary-btn";
        button.dataset.admEditClose = "";
        button.textContent = "Cancel";

        return button;
    }

    // ==========================================
    // OPEN / CLOSE MODAL
    // ==========================================

    function openModal(
        heading,
        description,
        source,
        kind = "standard"
    ) {
        if (loadingController) {
            loadingController.abort();
        }

        loadingController = null;

        clearPreview();
        setError("");

        opener = source || document.activeElement;

        dialog.dataset.modalKind = kind;

        title.textContent = heading;
        subtitle.textContent = description || "";

        content.replaceChildren();

        dialog.querySelector(
            ".adm-product-fixed-footer"
        )?.remove();

        if (!dialog.open) {
            dialog.showModal();
        }

        document.body.classList.add(
            "adm-modal-active"
        );

        content.scrollTop = 0;
    }

    function closeModal() {
        if (saving) {
            setError(
                "Please finish saving before closing this editor."
            );
            return;
        }

        if (loadingController) {
            loadingController.abort();
        }

        loadingController = null;

        if (dialog.open) {
            dialog.close();
        }
    }

    dialog.addEventListener("click", event => {

        const element =
            event.target instanceof Element
                ? event.target
                : null;

        if (element?.closest(CLOSE_SELECTOR)) {
            event.preventDefault();
            event.stopPropagation();
            closeModal();

        } else if (event.target === dialog) {
            closeModal();
        }

    }, true);

    dialog.addEventListener("cancel", event => {
        event.preventDefault();
        closeModal();
    });

    dialog.addEventListener("close", () => {

        document.body.classList.remove(
            "adm-modal-active"
        );

        dialog.querySelector(
            ".adm-product-fixed-footer"
        )?.remove();

        content.replaceChildren();

        setError("");
        clearPreview();

        delete dialog.dataset.modalKind;

        if (opener?.isConnected) {
            opener.focus({
                preventScroll: true
            });
        }

        opener = null;
    });

    // ==========================================
    // PREPARE FORM INSIDE MODAL
    // ==========================================

    function installForm(
        original,
        heading,
        description,
        trigger,
        template = null
    ) {
        let kind = "standard";

        const path = actionURL(original).pathname;

        if (original.matches(".adm-product-form")) {
            kind = "product";

        } else if (
            path.includes("delivery-areas") ||
            original.id === "delivery-area-form"
        ) {
            kind = "delivery";

        } else if (original.matches(".adm-mini-form")) {
            kind = "compact";
        }

        openModal(
            heading,
            description,
            trigger,
            kind
        );

        const form = original.cloneNode(true);

        form.querySelectorAll(
            "[data-modal-close]"
        ).forEach(button => {
            button.type = "button";
            button.dataset.admEditClose = "";
        });

        form.querySelectorAll(
            ".adm-form-actions a.adm-secondary-btn"
        ).forEach(link => {
            link.replaceWith(cancelButton());
        });

        if (original.dataset.confirm) {
            const note = document.createElement("p");

            note.className = "adm-modal-note";
            note.textContent = original.dataset.confirm;

            content.append(note);
        }

        content.append(form);

        // KEEP ACTIONS CONNECTED TO THEIR FORM

        const actions = form.querySelector(
            ".adm-form-actions"
        );

        if (actions) {
            if (!actions.querySelector(CLOSE_SELECTOR)) {
                actions.prepend(cancelButton());
            }

        } else if (!form.querySelector(CLOSE_SELECTOR)) {

            const footer = document.createElement("div");

            footer.className =
                "adm-modal-actions adm-modal-bottom-actions";

            footer.append(cancelButton());

            form.append(footer);
        }

        // ORGANIZE DIRECT SUBMIT BUTTONS

        const directButtons = [
            ...form.querySelectorAll(
                ':scope > button[type="submit"]'
            )
        ];

        if (directButtons.length) {

            let footer = form.querySelector(
                ":scope > .adm-modal-bottom-actions"
            );

            if (!footer) {
                footer = document.createElement("div");

                footer.className =
                    "adm-modal-actions adm-modal-bottom-actions";

                form.append(footer);
            }

            const left = document.createElement("div");
            const right = document.createElement("div");

            left.className = "adm-modal-actions-start";
            right.className = "adm-modal-actions-end";

            directButtons.forEach(button => {

                const destructive =
                    button.matches(".danger, .restore") ||
                    ["enable", "disable"].includes(
                        button.value
                    );

                (destructive ? left : right).append(button);

                if (!destructive) {
                    button.classList.add(
                        "adm-primary-btn"
                    );
                }
            });

            footer.replaceChildren(left, right);

            right.prepend(cancelButton());
        }

        // RECIPE INGREDIENT TEMPLATE

        if (template) {
            content.append(
                template.cloneNode(true)
            );
        }

        // PRODUCT DESCRIPTION COUNTER

        const descriptionField = form.querySelector(
            "[data-description]"
        );

        const descriptionCount = form.querySelector(
            "[data-description-count]"
        );

        if (descriptionField && descriptionCount) {
            descriptionCount.textContent =
                descriptionField.value.length;
        }

        const focusTarget = form.querySelector(
            'input:not([type="hidden"]):not([type="file"]):not([disabled]), ' +
            'select:not([disabled]), textarea:not([disabled])'
        );

        focusTarget?.focus({
            preventScroll: true
        });
    }

    // ==========================================
    // INLINE EDIT MODALS
    // ==========================================

    document.querySelectorAll(
        "details.adm-detail-toggle"
    ).forEach(details => {

        const form = details.querySelector("form");
        const summary = details.querySelector("summary");

        if (!form || !summary) return;

        const label = summary.textContent.trim();

        const heading =
            details.dataset.modalTitle || label;

        const rowName = details.closest("tr")
            ?.querySelector("td strong")
            ?.textContent.trim();

        const trigger = document.createElement("button");

        trigger.type = "button";
        trigger.className =
            "adm-action-button adm-modal-trigger";

        trigger.textContent = label;

        trigger.addEventListener("click", () => {

            installForm(
                form,
                heading,
                rowName
                    ? `Selected record: ${rowName}`
                    : "Update the details below, then save.",
                trigger
            );
        });

        details.replaceWith(trigger);
    });

    // ==========================================
    // ADD CATEGORY / DELIVERY AREA
    // ==========================================

    document.querySelectorAll(
        'form input[name="action"][value="add"]'
    ).forEach(input => {

        const form = input.closest("form");

        if (!form) return;

        const path = actionURL(form).pathname;

        const label = path.endsWith("/categories")
            ? "Add Category"
            : "Add Delivery Area";

        const trigger = document.createElement("button");

        trigger.type = "button";

        trigger.className =
            "adm-primary-btn adm-modal-trigger";

        trigger.textContent = "+ " + label;

        trigger.addEventListener("click", () => {

            installForm(
                form,
                label,
                "Complete the required fields and save.",
                trigger
            );
        });

        form.replaceWith(trigger);
    });

    // ==========================================
    // OPTIONAL STAFF CREATE MODAL
    // ==========================================

    document.querySelectorAll(
        "form[data-staff-modal]"
    ).forEach(form => {

        const kind = form.querySelector(
            '[name="staff_type"]'
        )?.value;

        const label = kind === "rider"
            ? "Add Delivery Rider"
            : "Add Bakery Staff";

        const trigger = document.createElement("button");

        trigger.type = "button";
        trigger.className =
            "adm-primary-btn adm-modal-trigger";

        trigger.textContent = "+ " + label;

        trigger.addEventListener("click", () => {

            installForm(
                form,
                label,
                "Enter staff account information.",
                trigger
            );
        });

        form.replaceWith(trigger);
    });

    // ==========================================
    // ADMIN STATUS ACTION MODALS
    // ==========================================

   
    const actionPattern =
        /\/(products\/\d+\/(availability|archive|restore)|orders\/\d+\/(status|payment)|customers\/\d+\/status|production\/costs\/\d+|stock-control\/\d+\/(archive|restore|remove))$/;

    document.querySelectorAll(
        "form[action]"
    ).forEach(form => {

        if (!actionPattern.test(
            actionURL(form).pathname
        )) {
            return;
        }

        const submit = form.querySelector(
            'button[type="submit"]'
        );

        if (!submit) return;

        const label = submit.textContent.trim();

        const trigger = document.createElement("button");

        trigger.type = "button";
        trigger.className =
            submit.className || "adm-action-button";

        trigger.textContent = label;

        const record = form.closest("tr")
            ?.querySelector("td strong")
            ?.textContent.trim();

        trigger.addEventListener("click", () => {

            installForm(
                form,
                label,
                record
                    ? `Selected record: ${record}`
                    : "Review this action before continuing.",
                trigger
            );
        });

        form.replaceWith(trigger);
    });

    // ==========================================
    // PRODUCT / RECIPE EDITOR
    // ==========================================

    async function loadEditor(link) {

        const url = new URL(
            link.dataset.modalUrl,
            location.href
        );

        if (url.origin !== location.origin) {
            return;
        }

        const label =
            link.dataset.modalTitle ||
            link.textContent.trim() ||
            "Edit Details";

        openModal(
            label,
            "Loading editor...",
            link,
            "product"
        );

        const loading = document.createElement("p");

        loading.className = "adm-modal-loading";
        loading.textContent = "Loading editor...";

        content.append(loading);

        const controller = new AbortController();

        loadingController = controller;

        try {

            const response = await fetch(url.href, {
                credentials: "same-origin",
                signal: controller.signal,
                headers: {
                    "Accept": "text/html"
                }
            });

            if (
                !response.ok ||
                (
                    response.redirected &&
                    new URL(response.url).pathname.startsWith(
                        "/auth/"
                    )
                )
            ) {
                throw new Error(
                    "The editor could not be loaded. Please sign in again if needed."
                );
            }

            const page = new DOMParser().parseFromString(
                await response.text(),
                "text/html"
            );

            if (
                controller.signal.aborted ||
                !dialog.open
            ) {
                return;
            }

            const form = page.querySelector(
                ".adm-product-form, #recipe-form"
            );

            if (!form) {
                throw new Error(
                    "Edit form was not found on the server response."
                );
            }

            if (!form.getAttribute("action")) {
                form.setAttribute(
                    "action",
                    url.href
                );
            }

            const heading = page.querySelector(
                ".adm-page-heading h1"
            )?.textContent.trim() || label;

            installForm(
                form,
                heading,
                "Make changes and save.",
                link,
                page.querySelector(
                    "#ingredient-template"
                )
            );

        } catch (error) {

            if (error.name === "AbortError") {
                return;
            }

            content.replaceChildren();

            setError(
                error.message ||
                "Could not load editor."
            );

            const fallback = document.createElement("a");

            fallback.href = url.href;
            fallback.className = "adm-secondary-btn";
            fallback.textContent = "Open full editor";

            content.append(fallback);

        } finally {

            if (loadingController === controller) {
                loadingController = null;
            }
        }
    }

    document.addEventListener("click", event => {

        const link =
            event.target instanceof Element
                ? event.target.closest(
                    "a[data-modal-url]"
                )
                : null;

        if (
            !link ||
            event.button !== 0 ||
            event.ctrlKey ||
            event.metaKey ||
            event.altKey ||
            event.shiftKey
        ) {
            return;
        }

        event.preventDefault();

        loadEditor(link);
    });

    // ==========================================
    // PRODUCT DESCRIPTION COUNTER
    // ==========================================

    content.addEventListener("input", event => {

        if (!event.target.matches(
            "[data-description]"
        )) {
            return;
        }

        const counter = content.querySelector(
            "[data-description-count]"
        );

        if (counter) {
            counter.textContent =
                event.target.value.length;
        }
    });

    // ==========================================
    // PRODUCT IMAGE PREVIEW
    // ==========================================

    content.addEventListener("change", event => {

        const input = event.target;

        if (!input.matches(
            'input[type="file"][name="image"]'
        )) {
            return;
        }

        const file = input.files?.[0];

        if (!file) return;

        if (
            ![
                "image/jpeg",
                "image/png",
                "image/webp"
            ].includes(file.type) ||
            file.size > 5 * 1024 * 1024
        ) {
            input.value = "";

            setError(
                "Upload a JPG, PNG, or WEBP image up to 5 MB."
            );
            return;
        }

        clearPreview();
        setError("");

        previewURL = URL.createObjectURL(file);

        const preview = content.querySelector(
            "[data-image-preview]"
        );

        if (preview) {

            const img = document.createElement("img");

            img.src = previewURL;
            img.alt = "Selected product photograph";

            preview.replaceChildren(img);
        }
    });

    // ==========================================
    // RECIPE INGREDIENT CONTROLS
    // ==========================================

    content.addEventListener("click", event => {

        const target =
            event.target instanceof Element
                ? event.target
                : null;

        if (!target) return;

        if (target.closest("#add-line")) {

            event.preventDefault();

            const lines = content.querySelector(
                "#recipe-lines"
            );

            const template = content.querySelector(
                "#ingredient-template"
            );

            if (
                lines &&
                template &&
                lines.children.length < 50
            ) {
                lines.append(
                    template.content.cloneNode(true)
                );
            }
        }

        const remove = target.closest(
            ".remove-line"
        );

        if (remove) {
            event.preventDefault();

            remove.closest(
                ".recipe-line"
            )?.remove();
        }
    });

    
    // ==========================================
    // SAVE MODAL USING FLASK
    // ==========================================

    dialog.addEventListener("submit", async (event) => {

        if (!(event.target instanceof HTMLFormElement)) {
            return;
        }

        event.preventDefault();

        if (saving) return;

        const form = event.target;
        const submitter = event.submitter;
        const url = actionURL(form);

        if (url.origin !== location.origin) {
            setError("Invalid form destination.");
            return;
        }

        if (!form.checkValidity() && !submitter?.formNoValidate) {
            form.reportValidity();
            return;
        }

        const data = new FormData(form);

        if (submitter?.name) {
            data.set(submitter.name, submitter.value);
        }

        saving = true;
        setError("");

        const buttons = [
            ...form.querySelectorAll('button[type="submit"]')
        ];

        buttons.forEach(button => {
            button.disabled = true;
        });

        const oldSubtitle = subtitle.textContent;
        subtitle.textContent = "Saving changes...";

        try {
            const response = await fetch(url.href, {
                method: "POST",
                credentials: "same-origin",
                body: data,
                redirect: "follow",
                headers: {
                    "X-Requested-With": "XMLHttpRequest"
                }
            });

            const finalURL = new URL(response.url);

            // Session expired or login required
            if (finalURL.pathname.startsWith("/auth/")) {
                location.assign(response.url);
                return;
            }

            const responseHTML = await response.text();

            const page = new DOMParser().parseFromString(
                responseHTML,
                "text/html"
            );

            const errorElements = page.querySelectorAll(
                ".adm-alert-danger, " +
                ".adm-alert-error, " +
                ".adm-alert-warning, " +
                ".staff-message-danger"
            );

            const successElements = page.querySelectorAll(
                ".adm-alert-success, " +
                ".staff-message-success"
            );

            const errors = [...errorElements]
                .map(el => el.textContent.trim())
                .filter(Boolean);

            const successes = [...successElements]
                .map(el => el.textContent.trim())
                .filter(Boolean);

            // Flask returned HTTP error
            if (!response.ok) {

                let message = errors.join("\n");

                if (!message) {
                    message =
                        `Server returned HTTP ${response.status}. ` +
                        "Check the Flask terminal for details.";
                }

                setError(message);
                return;
            }

            // Flask returned validation or database errors
            if (errors.length > 0) {
                setError(errors.join("\n"));
                return;
            }

            // Flask confirmed successful operation
            if (successes.length > 0) {
                location.reload();
                return;
            }

            // Unknown result: do not falsely report success
            console.warn(
                "No success or error message found in Flask response.",
                {
                    requestedURL: url.href,
                    responseURL: response.url,
                    redirected: response.redirected,
                    status: response.status
                }
            );

            setError(
                "The server did not confirm whether the " +
                "changes were saved. Refresh the page and " +
                "check the record before trying again."
            );

        } catch (error) {

            console.error("Inventory modal save failed:", error);

            setError(
                "Unable to complete the request. " +
                "Check your Flask connection and terminal."
            );

        } finally {

            saving = false;
            subtitle.textContent = oldSubtitle;

            buttons.forEach(button => {
                button.disabled = false;
            });
        }
    });
});