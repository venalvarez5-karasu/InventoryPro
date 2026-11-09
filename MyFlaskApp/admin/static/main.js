
"use strict";

document.addEventListener("DOMContentLoaded", () => {

    /* ======================================
       RESPONSIVE ADMIN SIDEBAR
       ====================================== */

    const sidebar = document.getElementById(
        "admin-sidebar"
    );

    const menuButton = document.querySelector(
        "[data-sidebar-toggle]"
    );

    if (sidebar && menuButton) {

        const backdrop = document.createElement("div");

        backdrop.className = "adm-sidebar-backdrop";
        backdrop.setAttribute("aria-hidden", "true");

        document.body.appendChild(backdrop);

        function setSidebar(open) {

            sidebar.classList.toggle(
                "is-open",
                open
            );

            backdrop.classList.toggle(
                "is-visible",
                open
            );

            document.body.classList.toggle(
                "adm-menu-open",
                open
            );

            menuButton.setAttribute(
                "aria-expanded",
                String(open)
            );

            menuButton.setAttribute(
                "aria-label",
                open ? "Close menu" : "Open menu"
            );
        }

        menuButton.addEventListener("click", () => {

            const isOpen = sidebar.classList.contains(
                "is-open"
            );

            setSidebar(!isOpen);
        });

        backdrop.addEventListener("click", () => {
            setSidebar(false);
        });

        document.addEventListener("keydown", (event) => {

            if (event.key === "Escape") {
                setSidebar(false);
            }
        });

        sidebar.querySelectorAll("a").forEach((link) => {

            link.addEventListener("click", () => {
                setSidebar(false);
            });
        });

        window.addEventListener("resize", () => {

            if (window.innerWidth > 760) {
                setSidebar(false);
            }
        });
    }


    /* ======================================
       PRODUCT IMAGE PREVIEW
       ====================================== */

    const imageInput = document.getElementById("image");

    const preview = document.querySelector(
        "[data-image-preview]"
    );

    let previewURL = null;

    if (imageInput && preview) {

        imageInput.addEventListener("change", () => {

            const file = imageInput.files[0];

            if (!file) return;

            const allowedTypes = [
                "image/jpeg",
                "image/png",
                "image/webp"
            ];

            if (!allowedTypes.includes(file.type)) {

                alert(
                    "Only JPG, PNG, and WEBP images are allowed."
                );

                imageInput.value = "";
                return;
            }

            if (file.size > 5 * 1024 * 1024) {

                alert(
                    "Image must not exceed 5 MB."
                );

                imageInput.value = "";
                return;
            }

            if (previewURL) {
                URL.revokeObjectURL(previewURL);
            }

            previewURL = URL.createObjectURL(file);

            const image = document.createElement("img");

            image.src = previewURL;
            image.alt = "Selected product photograph";

            preview.replaceChildren(image);
        });
    }


    /* ======================================
       ARCHIVE CONFIRMATION
       ====================================== */

    const confirmForms = document.querySelectorAll(
        "form[data-confirm]"
    );

    confirmForms.forEach((form) => {

        form.addEventListener("submit", (event) => {

            const message = form.dataset.confirm;

            if (!window.confirm(message)) {
                event.preventDefault();
            }
        });
    });

});
