
"use strict";

document.addEventListener("DOMContentLoaded", () => {

    const dialog = document.getElementById("adm-edit-dialog");
    if (!dialog || typeof dialog.showModal !== "function") return;

    const title = document.getElementById("adm-edit-title");
    const subtitle = document.getElementById("adm-edit-subtitle");
    const content = document.getElementById("adm-edit-content");
    const errorBox = document.getElementById("adm-edit-error");

    if (!title || !subtitle || !content || !errorBox) return;

    const CLOSE_SELECTOR =
        "[data-adm-edit-close], [data-modal-close]";

    let opener = null;
    let saving = false;
    let loadingController = null;
    let photoURL = null;

    // BASIC HELPERS

    function showError(message) {
        errorBox.textContent = message;
        errorBox.hidden = false;
    }

    function clearError() {
        errorBox.textContent = "";
        errorBox.hidden = true;
    }

    function releasePhoto() {
        if (photoURL) {
            URL.revokeObjectURL(photoURL);
            photoURL = null;
        }
    }

    function makeCancelButton() {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "adm-secondary-btn";
        button.setAttribute("data-adm-edit-close", "");
        button.textContent = "Cancel";
        return button;
    }

    // OPEN / CLOSE

    function openModal(name, description, trigger, kind = "standard") {

        if (loadingController) {
            loadingController.abort();
            loadingController = null;
        }

        releasePhoto();
        clearError();

        opener = trigger || document.activeElement;

        dialog.dataset.modalKind = kind;

        title.textContent = name;
        subtitle.textContent = description || "";

        content.replaceChildren();
        
        // Remove the previous product footer, if any.
        dialog.querySelector(
            ".adm-product-fixed-footer"
        )?.remove();

        content.replaceChildren();


        if (!dialog.open) {
            dialog.showModal();
        }

        document.body.classList.add("adm-modal-active");
        content.scrollTop = 0;
    }

    function closeModal() {

        if (saving) {
            showError(
                "Your changes are being saved. " +
                "The editor can close when saving finishes."
            );
            return;
        }

        if (loadingController) {
            loadingController.abort();
            loadingController = null;
        }

        if (dialog.open) {
            dialog.close();
        }
    }

    // IMPORTANT:
    // Supports BOTH attributes found in your templates.
    // Capture phase also prevents another click listener
    // from interfering with the close button.

    dialog.addEventListener("click", (event) => {

        const element = event.target instanceof Element
            ? event.target
            : null;

        if (!element) return;

        if (element.closest(CLOSE_SELECTOR)) {
            event.preventDefault();
            event.stopPropagation();
            closeModal();
            return;
        }

        if (event.target === dialog) {
            closeModal();
        }

    }, true);

    // Escape key
    dialog.addEventListener("cancel", (event) => {
        event.preventDefault();
        closeModal();
    });

    // Cleanup
    dialog.addEventListener("close", () => {

        document.body.classList.remove("adm-modal-active");
        dialog.querySelector(".adm-product-fixed-footer")?.remove();

        content.replaceChildren();
        clearError();
        releasePhoto();

        delete dialog.dataset.modalKind;

        if (opener && opener.isConnected) {
            opener.focus({ preventScroll: true });
        }

        opener = null;
    });

    // PREPARE FORM FOR MODAL

    function installForm(
        original,
        name,
        description,
        trigger,
        recipeTemplate = null
    ) {

        let kind = "standard";

        if (original.matches(".adm-product-form")) {
            kind = "product";
        } else if (
            original.matches(".adm-mini-form") &&
            /delivery-areas/.test(original.action)
        ) {
            kind = "delivery";
        } else if (original.matches(".adm-mini-form")) {
            kind = "compact";
        } else if (
            /delivery-areas/.test(original.action) ||
            original.id === "delivery-area-form"
        ) {
            kind = "delivery";
        }

        openModal(name, description, trigger, kind);

        const form = original.cloneNode(true);

        // Normalize existing Cancel buttons.
        form.querySelectorAll("[data-modal-close]").forEach((button) => {
            button.type = "button";
            button.setAttribute("data-adm-edit-close", "");
        });

        // Convert full-page Cancel links into buttons.
        form.querySelectorAll(
            ".adm-form-actions a.adm-secondary-btn"
        ).forEach((link) => {
            link.replaceWith(makeCancelButton());
        });

        // Supply a Cancel button only if missing.
        if (!form.querySelector(CLOSE_SELECTOR)) {

            const actions = form.querySelector(".adm-form-actions");

            if (actions) {
                actions.prepend(makeCancelButton());
            } else {
                const footer = document.createElement("div");
                footer.className = "adm-modal-actions";
                footer.append(makeCancelButton());
                form.append(footer);
            }
        }

        if (original.dataset.confirm) {
            const note = document.createElement("p");
            note.className = "adm-modal-note";
            note.textContent = original.dataset.confirm;
            content.append(note);
        }

        content.append(form);

        // KEEP PRODUCT ACTIONS VISIBLE
        // Works for both Add Product and Edit Product

        if (form.classList.contains("adm-product-form")) {

            const footer = form.querySelector(
                ".adm-form-actions"
            );

            const modalShell = dialog.querySelector(
                ".adm-edit-shell"
            );

            if (footer && modalShell) {

                // The form remains inside the scroll area.
                // The buttons remain associated with it.
                form.id = "adm-active-product-form";

                footer.querySelectorAll(
                    'button[type="submit"], input[type="submit"]'
                ).forEach((button) => {

                    button.setAttribute(
                        "form",
                        form.id
                    );

                });

                footer.classList.add(
                    "adm-product-fixed-footer"
                );

                // Move actions outside the scrolling content.
                modalShell.append(footer);
            }
        }

        // ORGANIZE MODAL ACTION BUTTONS
        // Cancel beside Save / Add

        const directSubmitButtons = Array.from(
            form.querySelectorAll(
                ':scope > button[type="submit"]'
            )
        );

        if (directSubmitButtons.length > 0) {

            let footer = form.querySelector(
                ":scope > .adm-modal-actions"
            );

            if (!footer) {
                footer = document.createElement("div");
                form.append(footer);
            }

            footer.className =
                "adm-modal-actions adm-modal-bottom-actions";

            let cancelButton = form.querySelector(
                "[data-adm-edit-close], [data-modal-close]"
            );

            if (!cancelButton) {
                cancelButton = makeCancelButton();
            }

            cancelButton.type = "button";

            // Keep destructive/category-status actions
            // separate from the primary Save button.

            const secondaryActions = directSubmitButtons.filter(
                button =>
                    button.value === "disable" ||
                    button.value === "enable" ||
                    button.classList.contains("danger") ||
                    button.classList.contains("restore")
            );

            const primaryActions = directSubmitButtons.filter(
                button => !secondaryActions.includes(button)
            );

            const leftActions = document.createElement("div");
            leftActions.className = "adm-modal-actions-start";

            const rightActions = document.createElement("div");
            rightActions.className = "adm-modal-actions-end";

            secondaryActions.forEach(button => {
                leftActions.append(button);
            });

            rightActions.append(cancelButton);

            primaryActions.forEach(button => {
                button.classList.add("adm-primary-btn");
                rightActions.append(button);
            });

            footer.replaceChildren(leftActions, rightActions);
        }


        if (recipeTemplate) {
            content.append(recipeTemplate.cloneNode(true));
        }

        const textarea = form.querySelector("[data-description]");
        const count = form.querySelector("[data-description-count]");

        if (textarea && count) {
            count.textContent = textarea.value.length;
        }

        content.scrollTop = 0;

        const firstField = form.querySelector(
            'input:not([type="hidden"]):not([type="file"]):not([disabled]), ' +
            'select:not([disabled]), textarea:not([disabled])'
        );

        if (firstField) {
            firstField.focus({ preventScroll: true });
        }
    }

    // INLINE EDIT FORMS
    // Categories, Delivery and Inventory

    document.querySelectorAll("details.adm-detail-toggle")
        .forEach((details) => {

            const original = details.querySelector("form");
            const summary = details.querySelector("summary");

            if (!original || !summary) return;

            const label = summary.textContent.trim();
            const name = details.dataset.modalTitle || label;

            const rowName = details.closest("tr")
                ?.querySelector("td strong")
                ?.textContent.trim();

            const trigger = document.createElement("button");
            trigger.type = "button";
            trigger.className = "adm-action-button adm-modal-trigger";
            trigger.textContent = label;

            trigger.addEventListener("click", () => {
                installForm(
                    original,
                    name,
                    rowName
                        ? "Selected record: " + rowName
                        : "Update the details below, then save.",
                    trigger
                );
            });

            details.replaceWith(trigger);
        });

    // ADD CATEGORY / DELIVERY AREA

    document.querySelectorAll(
        'form input[name="action"][value="add"]'
    ).forEach((input) => {

        const original = input.closest("form");
        if (!original) return;

        const isCategory = new URL(
            original.action, location.href
        ).pathname.endsWith("/categories");

        const name = isCategory
            ? "Add Category"
            : "Add Delivery Area";

        const trigger = document.createElement("button");

        trigger.type = "button";
        trigger.className = "adm-primary-btn adm-modal-trigger";
        trigger.textContent = "+ " + name;

        trigger.addEventListener("click", () => {
            installForm(
                original,
                name,
                "Complete the required fields and save.",
                trigger
            );
        });

        original.replaceWith(trigger);
    });

    // OTHER ADMIN ACTIONS

    const actionPattern =
        /\/(products\/\d+\/(availability|archive|restore)|orders\/\d+\/(status|payment)|customers\/\d+\/status|production\/costs\/\d+)$/;

    document.querySelectorAll("form[action]").forEach((original) => {

        const path = new URL(
            original.action, location.href
        ).pathname;

        if (!actionPattern.test(path)) return;

        const submit = original.querySelector('button[type="submit"]');
        if (!submit) return;

        const label = submit.textContent.trim();

        const trigger = document.createElement("button");
        trigger.type = "button";
        trigger.className = submit.className || "adm-action-button";
        trigger.textContent = label;

        const record = original.closest("tr")
            ?.querySelector("td strong")
            ?.textContent.trim();

        trigger.addEventListener("click", () => {
            installForm(
                original,
                label,
                record
                    ? "Selected record: " + record
                    : "Review the action before continuing.",
                trigger
            );
        });

        original.replaceWith(trigger);
    });

    // LOAD PRODUCT / RECIPE EDITOR

    async function loadEditor(link) {

        const url = new URL(
            link.dataset.modalUrl,
            location.href
        );

        if (url.origin !== location.origin) return;

        const label =
            link.dataset.modalTitle ||
            link.textContent.trim() ||
            "Edit Details";

        openModal(label, "Loading editor...", link, "product");

        const loader = document.createElement("p");
        loader.className = "adm-modal-loading";
        loader.textContent = "Loading editor...";
        content.append(loader);

        const controller = new AbortController();
        loadingController = controller;

        try {

            const response = await fetch(url.href, {
                credentials: "same-origin",
                signal: controller.signal
            });

            if (!response.ok) {
                throw new Error("Unable to load the editor.");
            }

            const page = new DOMParser().parseFromString(
                await response.text(),
                "text/html"
            );

            if (controller.signal.aborted || !dialog.open) return;

            const form = page.querySelector(
                ".adm-product-form, #recipe-form"
            );

            if (!form) {
                throw new Error("Edit form was not found.");
            }

            if (!form.getAttribute("action")) {
                form.action = url.href;
            }

            const pageTitle = page.querySelector(
                ".adm-page-heading h1"
            )?.textContent.trim() || label;

            // Recipe editor also needs its ingredient template.
            const recipeTemplate = page.querySelector(
                "#ingredient-template"
            );

            installForm(
                form,
                pageTitle,
                "Make changes and save without leaving this page.",
                link,
                recipeTemplate
            );

        } catch (error) {

            if (error.name === "AbortError") return;

            clearError();
            content.replaceChildren();

            showError(error.message || "Unable to load the editor.");

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

    document.addEventListener("click", (event) => {

        const link = event.target instanceof Element
            ? event.target.closest("a[data-modal-url]")
            : null;

        if (!link) return;

        if (
            event.ctrlKey ||
            event.metaKey ||
            event.shiftKey ||
            event.altKey ||
            event.button !== 0
        ) return;

        event.preventDefault();
        loadEditor(link);
    });

    // DESCRIPTION CHARACTER COUNTER

    content.addEventListener("input", (event) => {

        if (!event.target.matches("[data-description]")) return;

        const count = content.querySelector("[data-description-count]");

        if (count) {
            count.textContent = event.target.value.length;
        }
    });

    // PRODUCT IMAGE PREVIEW

    content.addEventListener("change", (event) => {

        const input = event.target;

        if (!input.matches('input[type="file"][name="image"]')) {
            return;
        }

        const file = input.files && input.files[0];
        if (!file) return;

        if (
            !["image/jpeg", "image/png", "image/webp"].includes(file.type) ||
            file.size > 5 * 1024 * 1024
        ) {
            input.value = "";
            showError("Upload a JPG, PNG or WEBP image up to 5 MB.");
            return;
        }

        releasePhoto();
        clearError();

        photoURL = URL.createObjectURL(file);

        const preview = content.querySelector("[data-image-preview]");

        if (preview) {
            const img = document.createElement("img");
            img.src = photoURL;
            img.alt = "New product photograph";
            preview.replaceChildren(img);
        }
    });

    // RECIPE INGREDIENT ROWS

    content.addEventListener("click", (event) => {

        if (event.target.closest("#add-line")) {

            const lines = content.querySelector("#recipe-lines");
            const template = content.querySelector("#ingredient-template");

            if (lines && template && lines.children.length < 50) {
                lines.append(template.content.cloneNode(true));
            }
        }

        const remove = event.target.closest(".remove-line");

        if (remove) {
            remove.closest(".recipe-line")?.remove();
        }
    });

    // SAVE WITHOUT CHANGING PAGE URL

    dialog.addEventListener("submit", async (event) => {

        if (!(event.target instanceof HTMLFormElement)) return;

        event.preventDefault();

        if (saving) return;

        const form = event.target;
        const button = event.submitter;

        const url = new URL(form.action, location.href);

        if (url.origin !== location.origin) {
            showError("Invalid form destination.");
            return;
        }

        const data = new FormData(form);

        // Preserve Save / Disable / Enable button values.
        if (button && button.name) {
            data.set(button.name, button.value);
        }

        clearError();
        saving = true;

        const buttons = [
            ...form.querySelectorAll('button[type="submit"]')
        ];

        buttons.forEach(item => item.disabled = true);

        const previousSubtitle = subtitle.textContent;
        subtitle.textContent = "Saving changes...";

        try {

            const response = await fetch(url.href, {
                method: "POST",
                body: data,
                credentials: "same-origin",
                redirect: "follow"
            });

            if (
                response.redirected &&
                new URL(response.url).pathname.startsWith("/auth/")
            ) {
                location.assign(response.url);
                return;
            }

            const page = new DOMParser().parseFromString(
                await response.text(),
                "text/html"
            );

            const errors = [
                ...page.querySelectorAll(
                    ".adm-alert-danger, .adm-alert-error, .adm-alert-warning"
                )
            ].map(el => el.textContent.trim()).filter(Boolean);

            if (!response.ok || errors.length > 0) {
                showError(
                    errors.join("\n") ||
                    "Could not save. Please check the information."
                );
                return;
            }

            if (!response.redirected) {
                showError(
                    "The server did not confirm the save. " +
                    "Please check the form."
                );
                return;
            }

            // Refresh the current listing, preserving its URL.
            location.reload();

        } catch (error) {

            showError(
                "Unable to connect to Flask. " +
                "The save was not confirmed."
            );

        } finally {

            saving = false;
            subtitle.textContent = previousSubtitle;

            buttons.forEach(item => item.disabled = false);
        }
    });

});
