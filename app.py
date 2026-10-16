"""
=============================================================================
Student Attendance Management System
A Simple, Robust BTech CSE Academic Project
Tech Stack: Python, Streamlit, SQLite, Pandas
=============================================================================
"""

import streamlit as st
import pandas as pd
import sqlite3
import datetime
import math
import os

# -----------------------------------------------------------------------------
# Configuration & Constants
# -----------------------------------------------------------------------------
DB_FILE = "attendance.db"
CRITERIA_PERCENTAGE = 75.0

BRANCH_OPTIONS = ["CSE", "IT", "ECE", "EE", "ME", "Civil", "AI & ML", "Data Science"]
SEMESTER_OPTIONS = [f"Semester {i}" for i in range(1, 9)]


# -----------------------------------------------------------------------------
# Database Engine & Helper Functions
# -----------------------------------------------------------------------------
def get_connection():
    """Create and return a database connection with foreign key support."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    """Initialize database tables, constraints, and indexes."""
    conn = get_connection()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roll_no TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                branch TEXT NOT NULL,
                semester TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('Present', 'Absent')),
                UNIQUE(student_id, date),
                FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_att_date ON attendance(date);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_att_student ON attendance(student_id);")
    conn.close()


def add_student(roll_no: str, name: str, branch: str, semester: str):
    """Add a new student record to the database with validation."""
    roll_no = roll_no.strip().upper()
    name = name.strip()
    if not roll_no or not name:
        return False, "Roll number and student name cannot be empty."

    conn = get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO students (roll_no, name, branch, semester) VALUES (?, ?, ?, ?)",
                (roll_no, name, branch, semester)
            )
        return True, f"Student '{name}' ({roll_no}) added successfully!"
    except sqlite3.IntegrityError:
        return False, f"Error: Roll Number '{roll_no}' already exists in the system."
    except Exception as e:
        return False, f"Database error: {str(e)}"
    finally:
        conn.close()


def delete_student(student_id: int):
    """Delete a student and cascade delete attendance records."""
    conn = get_connection()
    try:
        with conn:
            conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_all_students(search_query: str = "", branch: str = "All", semester: str = "All") -> pd.DataFrame:
    """Retrieve students with optional search query and filters."""
    conn = get_connection()
    query = "SELECT id, roll_no, name, branch, semester, created_at FROM students WHERE 1=1"
    params = []

    if branch and branch != "All":
        query += " AND branch = ?"
        params.append(branch)

    if semester and semester != "All":
        query += " AND semester = ?"
        params.append(semester)

    if search_query:
        search_pattern = f"%{search_query.strip()}%"
        query += " AND (roll_no LIKE ? OR name LIKE ?)"
        params.extend([search_pattern, search_pattern])

    query += " ORDER BY roll_no ASC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def get_attendance_for_date(date_str: str, branch: str = "All", semester: str = "All") -> pd.DataFrame:
    """
    Get students along with their attendance status for a given date.
    Returns: student_id, roll_no, name, branch, semester, status (None if unmarked)
    """
    conn = get_connection()
    query = """
        SELECT 
            s.id AS student_id,
            s.roll_no,
            s.name,
            s.branch,
            s.semester,
            a.status
        FROM students s
        LEFT JOIN attendance a 
            ON s.id = a.student_id AND a.date = ?
        WHERE 1=1
    """
    params = [date_str]

    if branch and branch != "All":
        query += " AND s.branch = ?"
        params.append(branch)

    if semester and semester != "All":
        query += " AND s.semester = ?"
        params.append(semester)

    query += " ORDER BY s.roll_no ASC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def save_bulk_attendance(records: list):
    """
    Save or update attendance records in bulk.
    records is a list of tuples: (student_id, date, status)
    """
    if not records:
        return 0
    conn = get_connection()
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO attendance (student_id, date, status) VALUES (?, ?, ?)",
            records
        )
    conn.close()
    return len(records)


def delete_attendance_date(date_str: str):
    """Delete all attendance entries for a particular date."""
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM attendance WHERE date = ?", (date_str,))
    conn.close()


def get_attendance_summary(branch: str = "All", semester: str = "All") -> pd.DataFrame:
    """
    Compute attendance summary per student:
    Roll No, Name, Branch, Semester, Total Classes, Present, Absent, Attendance %, Status, Classes Needed
    """
    conn = get_connection()
    query = """
        SELECT 
            s.id AS student_id,
            s.roll_no,
            s.name,
            s.branch,
            s.semester,
            COUNT(a.id) AS total_classes,
            COALESCE(SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END), 0) AS present_count,
            COALESCE(SUM(CASE WHEN a.status = 'Absent' THEN 1 ELSE 0 END), 0) AS absent_count
        FROM students s
        LEFT JOIN attendance a ON s.id = a.student_id
        WHERE 1=1
    """
    params = []
    if branch and branch != "All":
        query += " AND s.branch = ?"
        params.append(branch)
    if semester and semester != "All":
        query += " AND s.semester = ?"
        params.append(semester)

    query += " GROUP BY s.id, s.roll_no, s.name, s.branch, s.semester ORDER BY s.roll_no ASC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if df.empty:
        return df

    # Calculate percentage and target metrics
    def compute_metrics(row):
        total = row['total_classes']
        present = row['present_count']
        if total == 0:
            pct = 0.0
            status = "No Records"
            needed = 0
            bunks = 0
        else:
            pct = round((present / total) * 100.0, 2)
            if pct < CRITERIA_PERCENTAGE:
                status = f"Shortage (< {CRITERIA_PERCENTAGE:.0f}%)"
                # Consecutive classes needed: (P + x) / (T + x) >= 0.75  =>  x >= 3T - 4P
                needed = max(0, math.ceil(3 * total - 4 * present))
                bunks = 0
            else:
                status = f"Eligible (≥ {CRITERIA_PERCENTAGE:.0f}%)"
                needed = 0
                # Safe skips: P / (T + y) >= 0.75 => y <= (4P - 3T) / 3
                bunks = max(0, math.floor((4 * present - 3 * total) / 3))
        return pd.Series([pct, status, needed, bunks])

    df[['attendance_pct', 'eligibility', 'classes_needed_for_75', 'safe_bunks']] = df.apply(compute_metrics, axis=1)
    return df


def get_dashboard_stats():
    """Retrieve high-level metrics for dashboard cards."""
    conn = get_connection()
    
    total_students = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    total_dates = conn.execute("SELECT COUNT(DISTINCT date) FROM attendance").fetchone()[0]
    total_records = conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0]
    total_present = conn.execute("SELECT COUNT(*) FROM attendance WHERE status = 'Present'").fetchone()[0]

    overall_pct = round((total_present / total_records * 100.0), 1) if total_records > 0 else 0.0

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    today_marked = conn.execute("SELECT COUNT(*) FROM attendance WHERE date = ?", (today_str,)).fetchone()[0]
    today_present = conn.execute("SELECT COUNT(*) FROM attendance WHERE date = ? AND status = 'Present'", (today_str,)).fetchone()[0]
    today_absent = conn.execute("SELECT COUNT(*) FROM attendance WHERE date = ? AND status = 'Absent'", (today_str,)).fetchone()[0]

    conn.close()

    summary_df = get_attendance_summary()
    defaulters_count = 0
    if not summary_df.empty:
        active_summary = summary_df[summary_df['total_classes'] > 0]
        defaulters_count = len(active_summary[active_summary['attendance_pct'] < CRITERIA_PERCENTAGE])

    return {
        "total_students": total_students,
        "total_dates": total_dates,
        "overall_pct": overall_pct,
        "defaulters_count": defaulters_count,
        "today_str": today_str,
        "today_marked": today_marked > 0,
        "today_present": today_present,
        "today_absent": today_absent,
    }


def get_daily_trend() -> pd.DataFrame:
    """Retrieve date-wise aggregated stats for trend analytics."""
    conn = get_connection()
    query = """
        SELECT 
            date,
            COUNT(*) AS total_marked,
            SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) AS present_count,
            SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) AS absent_count,
            ROUND(SUM(CASE WHEN status = 'Present' THEN 1.0 ELSE 0.0 END) / COUNT(*) * 100.0, 1) AS attendance_pct
        FROM attendance
        GROUP BY date
        ORDER BY date ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def get_attendance_matrix() -> pd.DataFrame:
    """Generate attendance register grid: Students vs Dates."""
    conn = get_connection()
    query = """
        SELECT 
            s.roll_no AS "Roll No",
            s.name AS "Student Name",
            s.branch AS "Branch",
            a.date AS "Date",
            CASE WHEN a.status = 'Present' THEN 'P' ELSE 'A' END AS "Status"
        FROM students s
        JOIN attendance a ON s.id = a.student_id
        ORDER BY s.roll_no, a.date
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        return pd.DataFrame()

    pivot_df = df.pivot(
        index=["Roll No", "Student Name", "Branch"],
        columns="Date",
        values="Status"
    ).fillna("-").reset_index()
    return pivot_df


def seed_sample_data():
    """Populate realistic sample data for instant project demonstration."""
    conn = get_connection()
    with conn:
        count = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        if count > 0:
            return False, "Database already has records. Reset first if you want fresh demo data."

        students = [
            ("21BCSE01", "Aarav Sharma", "CSE", "Semester 6"),
            ("21BCSE02", "Ayush Verma", "CSE", "Semester 6"),
            ("21BCSE03", "Priya Patel", "CSE", "Semester 6"),
            ("21BCSE04", "Rohan Iyer", "CSE", "Semester 6"),
            ("21BCSE05", "Sneha Gupta", "CSE", "Semester 6"),
            ("21BCSE06", "Vikrant Singh", "CSE", "Semester 6"),
            ("21BCSE07", "Ananya Roy", "CSE", "Semester 6"),
            ("21BCSE08", "Tanmay Bhat", "CSE", "Semester 6"),
            ("21BCSE09", "Neha Reddy", "CSE", "Semester 6"),
            ("21BCSE10", "Siddharth Malhotra", "CSE", "Semester 6"),
            ("21BCSE11", "Divya Nair", "IT", "Semester 6"),
            ("21BCSE12", "Kabir Mehta", "IT", "Semester 6"),
        ]
        conn.executemany(
            "INSERT INTO students (roll_no, name, branch, semester) VALUES (?, ?, ?, ?)",
            students
        )

        cur = conn.execute("SELECT id, roll_no FROM students ORDER BY roll_no")
        student_map = {row[1]: row[0] for row in cur.fetchall()}

        # 10 recent weekdays
        today = datetime.date.today()
        dates = []
        d = today - datetime.timedelta(days=14)
        while len(dates) < 10 and d <= today:
            if d.weekday() < 5:
                dates.append(d.strftime("%Y-%m-%d"))
            d += datetime.timedelta(days=1)

        # Realistic attendance mix (includes students >= 75% and < 75%)
        patterns = {
            "21BCSE01": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1], # 100%
            "21BCSE02": [1, 1, 0, 1, 1, 1, 1, 1, 1, 1], # 90%
            "21BCSE03": [1, 1, 1, 0, 1, 1, 0, 1, 1, 1], # 80%
            "21BCSE04": [1, 1, 1, 1, 1, 0, 1, 1, 1, 1], # 90%
            "21BCSE05": [1, 0, 1, 1, 1, 1, 1, 0, 1, 1], # 80%
            "21BCSE06": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0], # 50% (Defaulter)
            "21BCSE07": [1, 1, 0, 0, 1, 1, 0, 1, 1, 0], # 60% (Defaulter)
            "21BCSE08": [0, 1, 0, 1, 0, 0, 1, 0, 1, 0], # 40% (Defaulter)
            "21BCSE09": [1, 1, 1, 1, 1, 1, 1, 1, 1, 0], # 90%
            "21BCSE10": [1, 1, 1, 1, 0, 1, 1, 1, 1, 1], # 90%
            "21BCSE11": [1, 1, 0, 1, 0, 1, 1, 0, 1, 1], # 70% (Defaulter)
            "21BCSE12": [1, 1, 1, 1, 1, 1, 1, 1, 0, 1], # 90%
        }

        att_records = []
        for roll, flags in patterns.items():
            sid = student_map[roll]
            for date_str, flag in zip(dates, flags):
                status = "Present" if flag == 1 else "Absent"
                att_records.append((sid, date_str, status))

        conn.executemany(
            "INSERT INTO attendance (student_id, date, status) VALUES (?, ?, ?)",
            att_records
        )

    conn.close()
    return True, f"Loaded 12 students and 10 days of class logs ({len(att_records)} records)."


def reset_database():
    """Drop and recreate tables for a clean slate."""
    conn = get_connection()
    with conn:
        conn.execute("DROP TABLE IF EXISTS attendance;")
        conn.execute("DROP TABLE IF EXISTS students;")
    conn.close()
    init_db()


# -----------------------------------------------------------------------------
# Main Application UI
# -----------------------------------------------------------------------------
def main():
    st.set_page_config(
        page_title="Student Attendance System",
        page_icon="🎓",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    init_db()

    # -------------------------------------------------------------------------
    # Sidebar
    # -------------------------------------------------------------------------
    with st.sidebar:
        st.title("🎓 Attendance System")
        st.markdown("**BTech CSE Academic Project**")
        st.caption("Python • Streamlit • SQLite • Pandas")
        st.markdown("---")

        menu = st.radio(
            "Navigation Menu",
            [
                "📊 Dashboard Overview",
                "📝 Mark Daily Attendance",
                "👨‍🎓 Student Management",
                "⚠️ Shortage List (< 75%)",
                "📥 Reports & CSV Export",
            ],
            index=0
        )

        st.markdown("---")
        st.markdown("### ⚡ Quick Demo Tools")

        if st.button("🚀 Load Sample Demo Data", use_container_width=True, help="Populate 12 students and 10 days of class logs"):
            success, msg = seed_sample_data()
            if success:
                st.success(msg)
                st.rerun()
            else:
                st.info(msg)

        with st.expander("⚠️ Danger Zone (Reset)"):
            st.write("Erase all students and attendance records from database.")
            if st.button("🗑️ Reset Database", type="secondary", use_container_width=True):
                reset_database()
                st.warning("Database has been reset to an empty state.")
                st.rerun()

        st.markdown("---")
        st.caption("Criteria: Minimum **75%** attendance required for examination eligibility.")

    # -------------------------------------------------------------------------
    # PAGE 1: 📊 Dashboard Overview
    # -------------------------------------------------------------------------
    if menu == "📊 Dashboard Overview":
        st.title("📊 Attendance Dashboard & Statistics")
        st.markdown("Real-time summary of student attendance, performance trends, and criteria compliance.")

        stats = get_dashboard_stats()

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("👥 Total Students", stats["total_students"])
        with col2:
            st.metric("📅 Total Class Sessions", stats["total_dates"])
        with col3:
            st.metric("📈 Overall Attendance", f"{stats['overall_pct']}%")
        with col4:
            st.metric(
                "⚠️ Shortage Defaulters (< 75%)", 
                stats["defaulters_count"], 
                delta=f"-{stats['defaulters_count']} At Risk" if stats["defaulters_count"] > 0 else "All Safe",
                delta_color="inverse"
            )

        st.markdown("---")

        t_col1, t_col2 = st.columns([2, 3])
        with t_col1:
            st.subheader("📅 Today's Attendance Snapshot")
            st.markdown(f"**Date:** `{stats['today_str']}`")
            if stats["today_marked"]:
                st.success(f"✅ Marked: **{stats['today_present']} Present**, **{stats['today_absent']} Absent**")
            else:
                st.warning("🔔 Attendance has not been marked for today yet.")
                st.caption("Head over to the 'Mark Daily Attendance' tab to record today's attendance.")

        with t_col2:
            st.subheader("🎯 Minimum 75% Criteria Status")
            summary_df = get_attendance_summary()
            if not summary_df.empty and stats["total_dates"] > 0:
                active_df = summary_df[summary_df["total_classes"] > 0]
                eligible_count = len(active_df[active_df["attendance_pct"] >= CRITERIA_PERCENTAGE])
                defaulter_count = len(active_df[active_df["attendance_pct"] < CRITERIA_PERCENTAGE])
                
                status_df = pd.DataFrame({
                    "Category": ["Eligible (≥ 75%)", "Shortage (< 75%)"],
                    "Students": [eligible_count, defaulter_count]
                }).set_index("Category")
                st.bar_chart(status_df, use_container_width=True)
            else:
                st.info("No attendance sessions recorded yet to display charts.")

        st.markdown("---")

        st.subheader("📈 Daily Attendance Trend")
        trend_df = get_daily_trend()
        if not trend_df.empty:
            chart_data = trend_df.set_index("date")[["present_count", "absent_count"]]
            st.bar_chart(chart_data, color=["#2e7d32", "#c62828"], use_container_width=True)
            st.caption("Green: Present Count | Red: Absent Count across recorded class dates.")
        else:
            st.info("No session trend available. Record attendance or load demo data to view charts.")

    # -------------------------------------------------------------------------
    # PAGE 2: 📝 Mark Daily Attendance
    # -------------------------------------------------------------------------
    elif menu == "📝 Mark Daily Attendance":
        st.title("📝 Mark Daily Student Attendance")
        st.markdown("Select a date and branch to mark students **Present** or **Absent**.")

        filter_col1, filter_col2, filter_col3 = st.columns([1.5, 1.5, 1.5])
        with filter_col1:
            selected_date = st.date_input("Select Date", value=datetime.date.today())
            date_str = selected_date.strftime("%Y-%m-%d")

        with filter_col2:
            branch_filter = st.selectbox("Filter Branch", ["All"] + BRANCH_OPTIONS)

        with filter_col3:
            sem_filter = st.selectbox("Filter Semester", ["All"] + SEMESTER_OPTIONS)

        att_df = get_attendance_for_date(date_str, branch_filter, sem_filter)

        if att_df.empty:
            st.warning("⚠️ No students found matching the selected filter. Please add students first.")
        else:
            marked_count = att_df["status"].notna().sum()
            if marked_count > 0:
                st.info(f"ℹ️ Attendance is already recorded for **{date_str}** ({marked_count} entries). You can edit and save updates.")
            else:
                st.caption(f"🔔 Attendance has not been saved yet for **{date_str}**. Mark Present/Absent below and click Save.")

            btn_col1, btn_col2, _ = st.columns([1.2, 1.2, 3])
            
            if "bulk_action" not in st.session_state:
                st.session_state.bulk_action = None

            with btn_col1:
                if st.button("✅ Mark All Present", use_container_width=True):
                    st.session_state.bulk_action = True
                    st.rerun()

            with btn_col2:
                if st.button("❌ Mark All Absent", use_container_width=True):
                    st.session_state.bulk_action = False
                    st.rerun()

            edit_display = att_df.copy()
            
            if st.session_state.bulk_action is True:
                edit_display["Present"] = True
                st.session_state.bulk_action = None
            elif st.session_state.bulk_action is False:
                edit_display["Present"] = False
                st.session_state.bulk_action = None
            else:
                edit_display["Present"] = edit_display["status"].apply(lambda s: True if s == "Present" or pd.isna(s) else False)

            edit_display = edit_display[["student_id", "roll_no", "name", "branch", "semester", "Present"]]

            edited_data = st.data_editor(
                edit_display,
                column_config={
                    "student_id": None,
                    "roll_no": st.column_config.TextColumn("Roll No", disabled=True),
                    "name": st.column_config.TextColumn("Student Name", disabled=True),
                    "branch": st.column_config.TextColumn("Branch", disabled=True),
                    "semester": st.column_config.TextColumn("Semester", disabled=True),
                    "Present": st.column_config.CheckboxColumn(
                        "Present (✓)",
                        help="Check to mark student Present, uncheck for Absent",
                        default=True
                    )
                },
                disabled=["student_id", "roll_no", "name", "branch", "semester"],
                hide_index=True,
                use_container_width=True,
                key=f"att_editor_{date_str}_{branch_filter}_{sem_filter}"
            )

            save_col1, save_col2, _ = st.columns([1.5, 1.5, 3])
            with save_col1:
                if st.button("💾 Save Attendance", type="primary", use_container_width=True):
                    records = []
                    p_cnt = 0
                    a_cnt = 0
                    for _, row in edited_data.iterrows():
                        st_val = "Present" if row["Present"] else "Absent"
                        if st_val == "Present":
                            p_cnt += 1
                        else:
                            a_cnt += 1
                        records.append((int(row["student_id"]), date_str, st_val))

                    saved = save_bulk_attendance(records)
                    st.success(f"🎉 Successfully saved attendance for {saved} students on {date_str}! ({p_cnt} Present, {a_cnt} Absent)")
                    st.rerun()

            with save_col2:
                if marked_count > 0:
                    if st.button("🗑️ Clear Date Records", type="secondary", use_container_width=True):
                        delete_attendance_date(date_str)
                        st.warning(f"Cleared attendance entries for {date_str}.")
                        st.rerun()

    # -------------------------------------------------------------------------
    # PAGE 3: 👨‍🎓 Student Management
    # -------------------------------------------------------------------------
    elif menu == "👨‍🎓 Student Management":
        st.title("👨‍🎓 Student Management")
        st.markdown("Register new students or search, filter, and manage existing student records.")

        tab1, tab2 = st.tabs(["➕ Add New Student", "🔍 Search & View Students"])

        with tab1:
            st.subheader("Register a New Student")
            with st.form("add_student_form", clear_on_submit=True):
                col_a, col_b = st.columns(2)
                with col_a:
                    roll_input = st.text_input("Roll Number *", placeholder="e.g. 21BCSE25").strip()
                    name_input = st.text_input("Full Name *", placeholder="e.g. Ayush Sharma").strip()
                with col_b:
                    branch_input = st.selectbox("Branch / Department *", BRANCH_OPTIONS)
                    sem_input = st.selectbox("Semester *", SEMESTER_OPTIONS, index=3)

                submitted = st.form_submit_button("➕ Add Student", use_container_width=True)
                if submitted:
                    if not roll_input or not name_input:
                        st.error("Please fill in both Roll Number and Full Name.")
                    else:
                        success, msg = add_student(roll_input, name_input, branch_input, sem_input)
                        if success:
                            st.success(msg)
                        else:
                            st.error(msg)

        with tab2:
            st.subheader("Student Directory")

            s_col1, s_col2, s_col3 = st.columns([2, 1, 1])
            with s_col1:
                search_query = st.text_input("🔍 Search by Name or Roll Number", placeholder="Type to filter...")
            with s_col2:
                branch_filter = st.selectbox("Filter by Branch", ["All"] + BRANCH_OPTIONS, key="stud_dir_branch")
            with s_col3:
                sem_filter = st.selectbox("Filter by Semester", ["All"] + SEMESTER_OPTIONS, key="stud_dir_sem")

            students_df = get_all_students(search_query, branch_filter, sem_filter)

            if students_df.empty:
                st.info("No students found matching the criteria.")
            else:
                st.caption(f"Showing **{len(students_df)}** registered students.")
                display_df = students_df.rename(columns={
                    "roll_no": "Roll Number",
                    "name": "Student Name",
                    "branch": "Branch",
                    "semester": "Semester",
                    "created_at": "Registration Date"
                })
                st.dataframe(display_df.drop(columns=["id"]), use_container_width=True, hide_index=True)

                with st.expander("🗑️ Delete a Student"):
                    st.caption("Deleting a student will also remove all their historical attendance records.")
                    student_options = {
                        f"{row['roll_no']} - {row['name']} ({row['branch']})": row['id']
                        for _, row in students_df.iterrows()
                    }
                    selected_student = st.selectbox("Select Student to Delete", list(student_options.keys()))
                    if st.button("Confirm Delete", type="primary"):
                        s_id = student_options[selected_student]
                        if delete_student(s_id):
                            st.success(f"Deleted {selected_student}")
                            st.rerun()
                        else:
                            st.error("Failed to delete student.")

    # -------------------------------------------------------------------------
    # PAGE 4: ⚠️ Shortage List (< 75%)
    # -------------------------------------------------------------------------
    elif menu == "⚠️ Shortage List (< 75%)":
        st.title("⚠️ Attendance Shortage & Defaulters")
        st.markdown(
            f"""
            **Academic Regulation:** Students with attendance strictly below **{CRITERIA_PERCENTAGE:.0f}%** 
            are marked as **Debarred / Critical** and are not eligible to appear in semester examinations.
            """
        )

        summary_df = get_attendance_summary()

        if summary_df.empty or summary_df["total_classes"].sum() == 0:
            st.info("No attendance records found yet. Mark attendance or load demo data to view the shortage list.")
        else:
            active_df = summary_df[summary_df["total_classes"] > 0]
            defaulters_df = active_df[active_df["attendance_pct"] < CRITERIA_PERCENTAGE].copy()

            d_col1, d_col2 = st.columns(2)
            with d_col1:
                st.metric(
                    "🚨 Total Shortage Defaulters",
                    len(defaulters_df),
                    help=f"Students having attendance less than {CRITERIA_PERCENTAGE}%"
                )
            with d_col2:
                pct_defaulters = round((len(defaulters_df) / len(active_df) * 100), 1) if len(active_df) > 0 else 0
                st.metric(
                    "📊 Defaulter Ratio",
                    f"{pct_defaulters}%",
                    help="Percentage of the active batch currently in shortage"
                )

            st.markdown("---")

            if defaulters_df.empty:
                st.success("🎉 Excellent! No students are currently below the 75% attendance threshold.")
            else:
                st.subheader("📋 Critical Students Shortage List")
                st.caption("Includes the exact number of consecutive classes required to reach the mandatory 75% mark.")

                view_defaulters = defaulters_df[[
                    "roll_no", "name", "branch", "semester", 
                    "total_classes", "present_count", "absent_count", 
                    "attendance_pct", "classes_needed_for_75"
                ]].rename(columns={
                    "roll_no": "Roll No",
                    "name": "Student Name",
                    "branch": "Branch",
                    "semester": "Semester",
                    "total_classes": "Total Classes",
                    "present_count": "Attended",
                    "absent_count": "Missed",
                    "attendance_pct": "Attendance %",
                    "classes_needed_for_75": "Classes Needed for 75%"
                })

                st.dataframe(
                    view_defaulters,
                    column_config={
                        "Attendance %": st.column_config.ProgressColumn(
                            "Attendance %",
                            format="%.1f%%",
                            min_value=0,
                            max_value=100
                        ),
                        "Classes Needed for 75%": st.column_config.NumberColumn(
                            "Classes Needed (75%)",
                            help="Consecutive future classes the student must attend to reach 75%"
                        )
                    },
                    use_container_width=True,
                    hide_index=True
                )

                csv_defaulters = view_defaulters.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Defaulters List (CSV)",
                    data=csv_defaulters,
                    file_name=f"defaulters_below_75_{datetime.date.today()}.csv",
                    mime="text/csv",
                    use_container_width=True
                )

    # -------------------------------------------------------------------------
    # PAGE 5: 📥 Reports & CSV Export
    # -------------------------------------------------------------------------
    elif menu == "📥 Reports & CSV Export":
        st.title("📥 Comprehensive Attendance Reports & Export")
        st.markdown("Download full official attendance sheets, daily registers, and shortage logs.")

        tab_rep1, tab_rep2, tab_rep3 = st.tabs([
            "📋 Master Attendance Report",
            "📅 Date-Wise Daily Log",
            "🗂️ Attendance Register Grid"
        ])

        with tab_rep1:
            st.subheader("Overall Student Attendance Sheet")

            f_col1, f_col2 = st.columns(2)
            with f_col1:
                rep_branch = st.selectbox("Select Branch", ["All"] + BRANCH_OPTIONS, key="rep_branch")
            with f_col2:
                rep_sem = st.selectbox("Select Semester", ["All"] + SEMESTER_OPTIONS, key="rep_sem")

            master_df = get_attendance_summary(rep_branch, rep_sem)

            if master_df.empty:
                st.info("No data available for the selected filters.")
            else:
                display_master = master_df[[
                    "roll_no", "name", "branch", "semester",
                    "total_classes", "present_count", "absent_count",
                    "attendance_pct", "eligibility", "classes_needed_for_75", "safe_bunks"
                ]].rename(columns={
                    "roll_no": "Roll No",
                    "name": "Student Name",
                    "branch": "Branch",
                    "semester": "Semester",
                    "total_classes": "Classes Held",
                    "present_count": "Attended",
                    "absent_count": "Absent",
                    "attendance_pct": "Attendance %",
                    "eligibility": "Status",
                    "classes_needed_for_75": "Classes Needed (75%)",
                    "safe_bunks": "Safe Misses Available"
                })

                def highlight_row(row):
                    if "< 75%" in str(row["Status"]):
                        return ["background-color: #ffebee; color: #b71c1c; font-weight: bold;"] * len(row)
                    elif "≥ 75%" in str(row["Status"]):
                        return ["background-color: #e8f5e9; color: #1b5e20;"] * len(row)
                    return [""] * len(row)

                styled_master = display_master.style.apply(highlight_row, axis=1)

                st.dataframe(styled_master, use_container_width=True, hide_index=True)

                csv_master = display_master.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Master Report (CSV)",
                    data=csv_master,
                    file_name=f"master_attendance_report_{datetime.date.today()}.csv",
                    mime="text/csv",
                    type="primary",
                    use_container_width=True
                )

        with tab_rep2:
            st.subheader("Daily Attendance Audit Log")
            log_date = st.date_input("Select Date for Daily Log", value=datetime.date.today(), key="log_date")
            log_date_str = log_date.strftime("%Y-%m-%d")

            conn = get_connection()
            query = """
                SELECT 
                    a.date AS "Date",
                    s.roll_no AS "Roll No",
                    s.name AS "Student Name",
                    s.branch AS "Branch",
                    s.semester AS "Semester",
                    a.status AS "Status"
                FROM attendance a
                JOIN students s ON a.student_id = s.id
                WHERE a.date = ?
                ORDER BY s.roll_no ASC
            """
            daily_log_df = pd.read_sql_query(query, conn, params=[log_date_str])
            conn.close()

            if daily_log_df.empty:
                st.info(f"No attendance records logged for {log_date_str}.")
            else:
                st.dataframe(daily_log_df, use_container_width=True, hide_index=True)

                csv_log = daily_log_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"📥 Download Daily Log for {log_date_str} (CSV)",
                    data=csv_log,
                    file_name=f"attendance_log_{log_date_str}.csv",
                    mime="text/csv",
                    use_container_width=True
                )

        with tab_rep3:
            st.subheader("Attendance Register (Dates vs Students)")
            st.caption("P = Present, A = Absent, - = No Class / Not Enrolled")

            matrix_df = get_attendance_matrix()
            if matrix_df.empty:
                st.info("No recorded attendance sessions to build register grid.")
            else:
                st.dataframe(matrix_df, use_container_width=True, hide_index=True)

                csv_matrix = matrix_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Attendance Register Grid (CSV)",
                    data=csv_matrix,
                    file_name=f"attendance_register_grid_{datetime.date.today()}.csv",
                    mime="text/csv",
                    use_container_width=True
                )


if __name__ == "__main__":
    main()
