document.addEventListener("DOMContentLoaded", function () {
    const taskSelect = document.getElementById("task");
    const dynamicFields = document.getElementById("dynamic-fields");
    const columnList = JSON.parse(document.getElementById("column-data").textContent);

    function createColumnSelect(name, labelText, multiple = false) {
        const wrapper = document.createElement("div");
        wrapper.classList.add("form-group");

        const label = document.createElement("label");
        label.setAttribute("for", name);
        label.innerText = labelText;
        wrapper.appendChild(label);

        const select = document.createElement("select");
        select.name = name;
        select.id = name;
        select.classList.add("form-control");

        if (multiple) {
            select.multiple = true;
            select.name = name + "[]";  // Allow array format for Flask
        }

        columnList.forEach(col => {
            const option = document.createElement("option");
            option.value = col;
            option.innerText = col;
            select.appendChild(option);
        });

        wrapper.appendChild(select);
        return wrapper;
    }

    function updateFields() {
        dynamicFields.innerHTML = "";

        const selectedTask = taskSelect.value;

        if (selectedTask === "simple_regression") {
            dynamicFields.appendChild(createColumnSelect("input_column", "Select Input Column"));
            dynamicFields.appendChild(createColumnSelect("output_column", "Select Output Column"));
        } else if (selectedTask === "multiple_regression") {
            dynamicFields.appendChild(createColumnSelect("input_columns", "Select Input Columns", true));
            dynamicFields.appendChild(createColumnSelect("output_column", "Select Output Column"));
        } else if (selectedTask === "one_sample_t_test") {
            dynamicFields.appendChild(createColumnSelect("column", "Select Column for T-Test"));
        }
    }

    taskSelect.addEventListener("change", updateFields);

    // Initial call in case a task is already selected
    if (taskSelect.value) {
        updateFields();
    }
});
