
"use strict";

document.addEventListener("DOMContentLoaded", () => {

    // RESPONSIVE ADMIN SIDEBAR

    const sidebar = document.getElementById("admin-sidebar");
    const toggle = document.querySelector(
        "[data-sidebar-toggle]"
    );
    const backdrop = document.querySelector(
        "[data-sidebar-backdrop]"
    );

    if (sidebar && toggle && backdrop) {
        function setSidebar(open) {
            sidebar.classList.toggle("is-open", open);
            backdrop.hidden = !open;

            document.body.classList.toggle(
                "adm-menu-open",
                open
            );

            toggle.setAttribute(
                "aria-expanded",
                String(open)
            );
        }

        toggle.addEventListener("click", () => {
            setSidebar(
                !sidebar.classList.contains("is-open")
            );
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
            if (window.innerWidth > 780) {
                setSidebar(false);
            }
        });

        setSidebar(false);
    }

    // PRODUCT IMAGE PREVIEW

    const imageInput = document.getElementById("image");
    const preview = document.querySelector(
        "[data-image-preview]"
    );

    let photoURL = null;

    if (imageInput && preview) {
        imageInput.addEventListener("change", () => {
            const file = imageInput.files?.[0];
            if (!file) return;

            if (
                !["image/jpeg", "image/png", "image/webp"].includes(file.type)
                || file.size > 5 * 1024 * 1024
            ) {
                imageInput.value = "";
                alert("Choose JPG, PNG, or WEBP up to 5 MB.");
                return;
            }

            if (photoURL) {
                URL.revokeObjectURL(photoURL);
            }

            photoURL = URL.createObjectURL(file);

            const img = document.createElement("img");
            img.src = photoURL;
            img.alt = "Selected product photograph";

            preview.replaceChildren(img);
        });

        window.addEventListener("pagehide", () => {
            if (photoURL) {
                URL.revokeObjectURL(photoURL);
            }
        });
    }

    // CONFIRM NON-MODAL ACTIONS

    document.querySelectorAll(
        "form[data-confirm]"
    ).forEach((form) => {
        form.addEventListener("submit", (event) => {
            const message = form.dataset.confirm;

            if (message && !window.confirm(message)) {
                event.preventDefault();
            }
        });
    });
});
