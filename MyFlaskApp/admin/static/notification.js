
"use strict";

document.addEventListener("DOMContentLoaded", () => {

    const menu = document.querySelector(
        "[data-admin-notification-menu]"
    );

    const dropdowns = Array.from(
        document.querySelectorAll(
            "[data-admin-dropdown]"
        )
    );

    dropdowns.forEach(dropdown => {

        dropdown.addEventListener("toggle", () => {

            if (!dropdown.open) return;

            dropdowns.forEach(other => {
                if (other !== dropdown) {
                    other.open = false;
                }
            });
        });
    });

    document.addEventListener("click", event => {

        dropdowns.forEach(dropdown => {

            if (
                dropdown.open &&
                !dropdown.contains(event.target)
            ) {
                dropdown.open = false;
            }
        });
    });

    document.addEventListener("keydown", event => {

        if (event.key === "Escape") {

            dropdowns.forEach(dropdown => {
                dropdown.open = false;
            });
        }
    });

    if (!menu) return;

    const feedURL = menu.dataset.notificationUrl;

    const badge = menu.querySelector(
        "[data-admin-notification-count]"
    );

    const summary = menu.querySelector(
        "[data-admin-notification-summary]"
    );

    const content = menu.querySelector(
        "[data-admin-notification-content]"
    );

    if (
        !feedURL ||
        !badge ||
        !summary ||
        !content
    ) {
        return;
    }

    const heading = menu.querySelector(
        ".adm-notification-heading"
    );

    const markAll = document.createElement("button");

    markAll.type = "button";
    markAll.className =
        "adm-secondary-btn adm-mark-all";

    markAll.textContent = "Mark all as read";

    heading?.append(markAll);

    const csrf = document.querySelector(
        'input[name="csrf_token"]'
    )?.value;

    const readURL = new URL(
        feedURL,
        location.href
    );

    readURL.pathname = readURL.pathname.replace(
        /\/notifications\.json$/,
        "/notifications/read"
    );

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

    async function markRead(payload) {

        const response = await fetch(
            readURL.href,
            {
                method: "POST",
                credentials: "same-origin",

                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrf || "",
                },

                body: JSON.stringify(payload),
            }
        );

        if (!response.ok) {
            throw new Error(
                "Could not update notification status."
            );
        }

        return response.json();
    }

    function notificationRow(item) {

        const wrapper = element(
            "div",
            "adm-notification-row" +
            (item.read ? " is-read" : "")
        );

        const link = element(
            "a",
            "adm-notification-item" +
            (
                item.important && !item.read
                    ? " is-important"
                    : ""
            )
        );

        link.href = item.url;

        const top = element(
            "div",
            "adm-notification-item-top"
        );

        top.append(
            element(
                "span",
                "adm-notification-label",
                item.label
            ),
            element(
                "small",
                "adm-notification-time",
                item.time || ""
            )
        );

        link.append(
            top,
            element(
                "strong",
                "adm-notification-item-title",
                item.title
            ),
            element(
                "p",
                "adm-notification-item-description",
                item.description
            )
        );

        link.addEventListener("click", event => {

            if (item.read) return;

            event.preventDefault();

            const destination = link.href;

            markRead({
                key: item.key
            })
                .catch(console.error)
                .finally(() => {
                    location.assign(destination);
                });
        });

        wrapper.append(link);

        if (!item.read) {

            const button = element(
                "button",
                "adm-mark-read",
                "Mark as read"
            );

            button.type = "button";

            button.addEventListener(
                "click",
                async () => {

                    button.disabled = true;

                    try {

                        await markRead({
                            key: item.key
                        });

                        await refreshNotifications();

                    } catch (error) {

                        alert(error.message);
                        button.disabled = false;
                    }
                }
            );

            wrapper.append(button);
        }

        return wrapper;
    }

    async function refreshNotifications() {

        if (refreshing) return;

        refreshing = true;

        try {

            const response = await fetch(
                feedURL,
                {
                    method: "GET",
                    credentials: "same-origin",
                    cache: "no-store",

                    headers: {
                        "Accept": "application/json"
                    },
                }
            );

            if (
                !response.ok ||
                response.redirected
            ) {
                throw new Error(
                    "Unable to retrieve notifications."
                );
            }

            const data = await response.json();

            const unreadCount = Number(
                data.attention_count || 0
            );

            badge.hidden = unreadCount === 0;

            badge.textContent = (
                unreadCount > 99
                    ? "99+"
                    : String(unreadCount)
            );

            summary.textContent =
                `${data.pending_count} unread orders / ` +
                `${data.low_stock_count} stock alerts`;

            markAll.disabled = unreadCount === 0;

            const fragment =
                document.createDocumentFragment();

            const orders = Array.isArray(data.orders)
                ? data.orders
                : [];

            const stock = Array.isArray(
                data.stock_items
            )
                ? data.stock_items
                : [];

            fragment.append(
                element(
                    "div",
                    "adm-notification-section-title",
                    `Recent Orders · ${orders.length}`
                )
            );

            if (!orders.length) {

                fragment.append(
                    element(
                        "p",
                        "adm-notification-empty",
                        "No recent orders."
                    )
                );
            }

            orders.forEach(order => {

                fragment.append(
                    notificationRow({
                        key: order.key,
                        read: order.read,
                        url: order.url,
                        label: order.status,
                        title:
                            `#${order.number} - ${order.customer}`,
                        description: order.products,
                        time: order.time,
                        important: [
                            "Pending",
                            "Pending Verification"
                        ].includes(order.status),
                    })
                );
            });

            fragment.append(
                element(
                    "div",
                    "adm-notification-section-title",
                    `Restock Needed · ${stock.length}`
                )
            );

            if (!stock.length) {

                fragment.append(
                    element(
                        "p",
                        "adm-notification-empty",
                        "No stock alerts."
                    )
                );
            }

            stock.forEach(item => {

                fragment.append(
                    notificationRow({
                        key: item.key,
                        read: item.read,
                        url: item.url,
                        label: item.status,
                        title: item.name,
                        description:
                            `On hand: ${item.quantity} ${item.unit}. ` +
                            `Reorder level: ${item.reorder_level}.`,
                        time: "Inventory",
                        important: true,
                    })
                );
            });

            content.replaceChildren(fragment);

        } catch (error) {

            console.error(error);

            summary.textContent =
                "Notification refresh unavailable";

        } finally {

            refreshing = false;
        }
    }

    markAll.addEventListener(
        "click",
        async () => {

            markAll.disabled = true;

            try {

                await markRead({
                    all: true
                });

                await refreshNotifications();

            } catch (error) {

                alert(error.message);
                markAll.disabled = false;
            }
        }
    );

    refreshNotifications();

    menu.addEventListener("toggle", () => {

        if (menu.open) {
            refreshNotifications();
        }
    });

    window.setInterval(() => {

        if (!document.hidden) {
            refreshNotifications();
        }

    }, 60000);

    document.addEventListener(
        "visibilitychange",
        () => {

            if (!document.hidden) {
                refreshNotifications();
            }
        }
    );
});
