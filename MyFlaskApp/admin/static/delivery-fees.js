
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const config = document.getElementById("adm-distance-config");

    // Do nothing on other Admin pages.
    if (!config) return;

    const lookupURL = config.dataset.lookupUrl;
    const modalContent = document.getElementById("adm-edit-content");

    const prepared = new WeakSet();
    const requestVersion = new WeakMap();

    // Local cities and municipalities.
    // Road distances are retrieved from MySQL.
    const CITY_OPTIONS = {
        laguna: [
            "Alaminos", "Bay", "Biñan", "Cabuyao",
            "Calamba", "Calauan", "Cavinti", "Famy",
            "Kalayaan", "Liliw", "Los Baños", "Luisiana",
            "Lumban", "Mabitac", "Magdalena", "Majayjay",
            "Nagcarlan", "Paete", "Pagsanjan", "Pakil",
            "Pangil", "Pila", "Rizal", "San Pablo",
            "San Pedro", "Santa Cruz", "Santa Maria",
            "Santa Rosa", "Siniloan", "Victoria"
        ],

        cavite: [
            "Alfonso", "Amadeo", "Bacoor", "Carmona",
            "Cavite City", "Dasmariñas",
            "General Emilio Aguinaldo",
            "General Mariano Alvarez", "General Trias",
            "Imus", "Indang", "Kawit", "Magallanes",
            "Maragondon", "Mendez", "Naic", "Noveleta",
            "Rosario", "Silang", "Tagaytay", "Tanza",
            "Ternate", "Trece Martires"
        ],

        ncr: [
            "Caloocan", "Las Piñas", "Makati", "Malabon",
            "Mandaluyong", "Manila", "Marikina",
            "Muntinlupa", "Navotas", "Parañaque",
            "Pasay", "Pasig", "Pateros", "Quezon City",
            "San Juan", "Taguig", "Valenzuela"
        ]
    };

    // Approved InventoryPro delivery fee tiers.
    const tiers = [
        [5, 15],
        [15, 20],
        [25, 30],
        [50, 40],
        [75, 50],
        [100, 65]
    ];

    const money = new Intl.NumberFormat("en-PH", {
        style: "currency",
        currency: "PHP",
        minimumFractionDigits: 2
    });

    const normalized = (value) => String(value || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, " ")
        .trim();

    function regionGroup(regionSelect) {
        const selected = regionSelect.selectedOptions[0];
        const label = normalized(selected?.textContent);

        if (label.includes("laguna")) return "laguna";
        if (label.includes("cavite")) return "cavite";

        if (
            label.includes("metro manila") ||
            label.includes("ncr") ||
            label.includes("national capital region")
        ) {
            return "ncr";
        }

        return null;
    }

    function parts(form) {
        return {
            region: form.querySelector(
                'select[name="region_id"]'
            ),
            city: form.querySelector(
                '[name="city_municipality"]'
            ),
            km: form.querySelector(
                'input[name="estimated_distance_km"]'
            ),
            amount: form.querySelector(
                "[data-delivery-fee]"
            ),
            note: form.querySelector(
                "[data-delivery-note]"
            ),
            enabled: form.querySelector(
                '[name="is_enabled"]'
            ),
            cod: form.querySelector(
                '[name="cod_enabled"]'
            )
        };
    }

    // Convert existing text input to dropdown.
    // No HTML file changes required.
    function fillCities(form, remembered = "") {
        const { region, city } = parts(form);

        if (
            !(city instanceof HTMLSelectElement) ||
            !region
        ) return;

        const group = regionGroup(region);
        const list = group ? CITY_OPTIONS[group] : [];

        city.replaceChildren(
            new Option(
                group
                    ? "Select city / municipality"
                    : "Select a supported region first",
                ""
            )
        );

        list.forEach((name) => {
            city.add(new Option(name, name));
        });

        city.disabled = !group;
        city.required = true;

        const match = list.find(
            (name) => normalized(name) === normalized(remembered)
        );

        if (match) {
            city.value = match;
        } else if (
            remembered &&
            form.querySelector(
                'input[name="action"][value="update"]'
            )
        ) {
            // Preserve an older existing city record.
            city.add(
                new Option(
                    `${remembered} (existing record)`,
                    remembered
                )
            );

            city.value = remembered;
        } else {
            city.value = "";
        }
    }

    function preview(form, message = "") {
        const p = parts(form);

        if (!p.km || !p.amount || !p.note) return;

        const raw = p.km.value.trim();

        if (!raw) {
            const oldFee = form.dataset.legacyLocation === "1"
                ? form.dataset.existingFee
                : "";

            p.amount.textContent =
                oldFee !== undefined && oldFee !== ""
                    ? money.format(Number(oldFee))
                    : "Distance not configured";

            p.note.textContent = message || (
                oldFee !== undefined && oldFee !== ""
                    ? "Previous saved fee. Enter a verified distance to use the new tiers."
                    : "Choose a city to check for a previously saved distance."
            );

            return;
        }

        const km = Number(raw);

        if (
            !Number.isFinite(km) ||
            km < 0 ||
            km > 99999.99
        ) {
            p.amount.textContent = "Invalid distance";
            p.note.textContent =
                "Enter a valid road-distance estimate.";
            return;
        }

        const tier = tiers.find(
            ([maximum]) => km <= maximum
        );

        if (!tier) {
            p.amount.textContent = "Manual quotation required";
            p.note.textContent =
                "Destinations over 100 km cannot use automatic delivery.";

            if (p.enabled) p.enabled.checked = false;
            if (p.cod) p.cod.checked = false;

            return;
        }

        p.amount.textContent = money.format(tier[1]);

        p.note.textContent = message ||
            "Fee follows the approved delivery distance tiers.";
    }

    function invalidateRequests(form) {
        const version =
            (requestVersion.get(form) || 0) + 1;

        requestVersion.set(form, version);
        return version;
    }

    // Check existing local route-distance records.
    async function lookup(form) {
        const p = parts(form);

        if (
            !p.region ||
            !p.city ||
            !p.km ||
            !p.region.value ||
            !p.city.value
        ) {
            preview(form, "Select a region and city first.");
            return;
        }

        const version = invalidateRequests(form);

        preview(
            form,
            "Checking saved road-distance estimates..."
        );

        try {
            const url = new URL(
                lookupURL,
                location.origin
            );

            url.searchParams.set(
                "region_id",
                p.region.value
            );

            url.searchParams.set(
                "city",
                p.city.value
            );

            const response = await fetch(url.href, {
                credentials: "same-origin",
                cache: "no-store",
                headers: {
                    Accept: "application/json"
                }
            });

            const data = await response.json();

            // Prevent older lookups from replacing newer values.
            if (
                !form.isConnected ||
                requestVersion.get(form) !== version
            ) return;

            if (!response.ok) {
                preview(
                    form,
                    data.message ||
                    "Could not check this destination."
                );
                return;
            }

            if (data.found) {
                p.km.value = data.distance_km;

                preview(
                    form,
                    "Saved route estimate loaded. Please verify before saving."
                );
            } else {
                preview(
                    form,
                    data.message ||
                    "No saved route. Enter verified km once."
                );
            }

        } catch (error) {
            if (requestVersion.get(form) === version) {
                preview(
                    form,
                    "Lookup unavailable. Enter a verified distance manually."
                );
            }
        }
    }

    function prepare(form) {
        if (prepared.has(form)) return;

        const p = parts(form);

        if (
            !p.region ||
            !p.city ||
            !p.km ||
            !p.amount
        ) return;

        prepared.add(form);

        const previousCity = p.city.value;

        // Replace City text input with a select.
        if (!(p.city instanceof HTMLSelectElement)) {
            const select = document.createElement("select");

            select.name = "city_municipality";
            select.required = true;
            select.className = p.city.className;

            if (p.city.id) {
                select.id = p.city.id;
            }

            p.city.replaceWith(select);
        }

        form.dataset.legacyLocation = "1";

        fillCities(form, previousCity);
        preview(form);

        // Load existing distance if available.
        if (previousCity && !p.km.value.trim()) {
            lookup(form);
        }
    }

    function prepareForms() {
        document.querySelectorAll(
            "[data-distance-form]"
        ).forEach(prepare);
    }

    prepareForms();

    // Add/Edit forms are cloned by modal.js.
    // Initialize their dropdowns once inserted.
    if (modalContent) {
        new MutationObserver(prepareForms).observe(
            modalContent,
            {
                childList: true,
                subtree: true
            }
        );
    }

    document.addEventListener("change", (event) => {
        const field = event.target;

        if (!(field instanceof Element)) return;

        const form = field.closest(
            "[data-distance-form]"
        );

        if (!form) return;

        prepare(form);

        const p = parts(form);

        if (field === p.region) {
            invalidateRequests(form);

            form.dataset.legacyLocation = "0";
            p.km.value = "";

            fillCities(form);

            preview(
                form,
                "Choose a city / municipality."
            );

        } else if (field === p.city) {
            invalidateRequests(form);

            form.dataset.legacyLocation = "0";
            p.km.value = "";

            lookup(form);
        }
    });

    document.addEventListener("input", (event) => {
        const field = event.target;

        if (!(field instanceof Element)) return;

        const form = field.closest(
            "[data-distance-form]"
        );

        if (!form) return;

        if (
            field.matches(
                'input[name="estimated_distance_km"]'
            )
        ) {
            // Prevent a late lookup from overwriting
            // manually entered kilometers.
            invalidateRequests(form);

            preview(
                form,
                "Admin-entered road estimate. Verify before saving."
            );
        }
    });
});
