
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const notificationMenu = document.querySelector(
        "[data-admin-notification-menu]"
    );

    const profileMenu = document.querySelector(
        "[data-admin-profile-menu]"
    );

    const dropdowns = document.querySelectorAll(
        "[data-admin-dropdown]"
    );

    // Close other dropdowns when opening one.
    dropdowns.forEach((dropdown) => {
        dropdown.addEventListener("toggle", () => {
            if (!dropdown.open) return;

            dropdowns.forEach((other) => {
                if (other !== dropdown) {
                    other.open = false;
                }
            });
        });
    });

    // Close when clicking outside.
    document.addEventListener("click", (event) => {
        dropdowns.forEach((dropdown) => {
            if (
                dropdown.open &&
                !dropdown.contains(event.target)
            ) {
                dropdown.open = false;
            }
        });
    });

    // Escape closes either menu.
    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;

        dropdowns.forEach((dropdown) => {
            dropdown.open = false;
        });
    });

    if (!notificationMenu) return;

    const feedURL = notificationMenu.dataset.notificationUrl;

    const badge = notificationMenu.querySelector(
        "[data-admin-notification-count]"
    );

    const summary = notificationMenu.querySelector(
        "[data-admin-notification-summary]"
    );

    const content = notificationMenu.querySelector(
        "[data-admin-notification-content]"
    );

    if (!feedURL || !badge || !summary || !content) return;

    let refreshing = false;

    function element(tag, className, text) {
        const node = document.createElement(tag);

        if (className) {
            node.className = className;
        }

        if (text !== undefined && text !== null) {
            node.textContent = String(text);
        }

        return node;
    }

    function sectionTitle(title, count) {
        const heading = element(
            "div",
            "adm-notification-section-title"
        );

        heading.append(
            element("strong", "", title),
            element("span", "", String(count))
        );

        return heading;
    }

    function notificationItem({
        label,
        heading,
        description,
        meta,
        url,
        important = false
    }) {
        const link = element(
            "a",
            "adm-notification-item" +
            (important ? " is-important" : "")
        );

        link.href = url;

        const top = element(
            "div",
            "adm-notification-item-top"
        );

        top.append(
            element("span", "adm-notification-label", label),
            element("small", "adm-notification-time", meta)
        );

        const name = element(
            "strong",
            "adm-notification-item-title",
            heading
        );

        const descriptionNode = element(
            "p",
            "adm-notification-item-description",
            description
        );

        link.append(top, name, descriptionNode);

        return link;
    }

    function renderNotifications(data) {
        const pending = Number(data.pending_count || 0);
        const lowStock = Number(data.low_stock_count || 0);
        const attention = pending + lowStock;

        badge.hidden = attention === 0;
        badge.textContent = attention > 99
            ? "99+"
            : String(attention);

        summary.textContent =
            `${pending} awaiting review / ` +
            `${lowStock} stock alerts`;

        const fragment = document.createDocumentFragment();

        // --------------------------------------
        // MOST RECENT CUSTOMER ORDERS
        // --------------------------------------

        const orders = Array.isArray(data.orders)
            ? data.orders
            : [];

        fragment.append(
            sectionTitle("Recent Orders", orders.length)
        );

        if (!orders.length) {
            fragment.append(
                element(
                    "p",
                    "adm-notification-empty",
                    "No customer orders yet."
                )
            );
        }

        orders.forEach((order) => {
            const status = String(order.status || "Pending");

            const important = [
                "Pending",
                "Pending Verification"
            ].includes(status);

            fragment.append(
                notificationItem({
                    label: important
                        ? "Needs review"
                        : status,

                    heading:
                        `#${order.number} - ${order.customer}`,

                    description:
                        order.products || "View order details.",

                    meta:
                        order.time || "",

                    url:
                        order.url,

                    important
                })
            );
        });

        // --------------------------------------
        // LOW STOCK / RESTOCK NOTIFICATIONS
        // --------------------------------------

        const stock = Array.isArray(data.stock_items)
            ? data.stock_items
            : [];

        fragment.append(
            sectionTitle("Restock Needed", lowStock)
        );

        if (!stock.length) {
            fragment.append(
                element(
                    "p",
                    "adm-notification-empty",
                    "No stock alerts at the moment."
                )
            );
        }

        stock.forEach((item) => {
            const quantity =
                `${item.quantity} ${item.unit}`;

            const threshold =
                `${item.reorder_level} ${item.unit}`;

            fragment.append(
                notificationItem({
                    label: item.status,

                    heading: item.name,

                    description:
                        `On hand: ${quantity}. ` +
                        `Reorder level: ${threshold}.`,

                    meta: "Inventory",

                    url: item.url,

                    important: true
                })
            );
        });

        content.replaceChildren(fragment);
    }

    async function refreshNotifications() {
        if (refreshing) return;

        refreshing = true;

        try {
            const response = await fetch(feedURL, {
                method: "GET",
                credentials: "same-origin",
                cache: "no-store",
                headers: {
                    "Accept": "application/json"
                }
            });

            if (!response.ok || response.redirected) {
                throw new Error(
                    "Unable to retrieve Admin notifications."
                );
            }

            const data = await response.json();

            renderNotifications(data);

        } catch (error) {
            if (!content.querySelector(
                ".adm-notification-item"
            )) {
                content.replaceChildren(
                    element(
                        "p",
                        "adm-notification-empty",
                        "Notifications are unavailable. " +
                        "Please refresh or sign in again."
                    )
                );
            }

            summary.textContent =
                "Notification refresh unavailable";

        } finally {
            refreshing = false;
        }
    }

    // Initial load.
    refreshNotifications();

    // Refresh when the notification menu opens.
    notificationMenu.addEventListener("toggle", () => {
        if (notificationMenu.open) {
            refreshNotifications();
        }
    });

    // Update every 60 seconds while the page is visible.
    window.setInterval(() => {
        if (!document.hidden) {
            refreshNotifications();
        }
    }, 60000);

    // Also update when returning to the Admin tab.
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) {
            refreshNotifications();
        }
    });
});
