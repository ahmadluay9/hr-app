from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import date, timedelta
from enum import Enum

# --- Enums for controlled vocabularies ---

class LeaveStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class LeaveType(str, Enum):
    VACATION = "vacation"
    SICK = "sick"
    PERSONAL = "personal"

# --- Pydantic Models for Data Validation ---

class LeaveBalance(BaseModel):
    allocated: int = 15
    used: int = 0
    
    @property
    def remaining(self) -> int:
        return self.allocated - self.used

class EmployeeBalances(BaseModel):
    vacation: LeaveBalance = Field(default_factory=LeaveBalance)
    sick: LeaveBalance = Field(default_factory=lambda: LeaveBalance(allocated=10))
    personal: LeaveBalance = Field(default_factory=lambda: LeaveBalance(allocated=5))

class Employee(BaseModel):
    id: int
    name: str
    position: str
    department: str
    leave_balances: EmployeeBalances = Field(default_factory=EmployeeBalances)

class CreateEmployee(BaseModel):
    name: str
    position: str
    department: str

class LeaveRequest(BaseModel):
    id: int
    employee_id: int
    leave_type: LeaveType
    start_date: date
    end_date: date
    reason: str
    status: LeaveStatus = LeaveStatus.PENDING

class CreateLeaveRequest(BaseModel):
    leave_type: LeaveType
    start_date: date
    end_date: date
    reason: str = Field(..., max_length=300)

class UpdateLeaveStatus(BaseModel):
    status: LeaveStatus


# --- In-Memory Databases ---

employee_db: List[Employee] = [
    Employee(id=1, name="Alice Smith", position="Software Engineer", department="Technology"),
    Employee(id=2, name="Bob Johnson", position="HR Manager", department="Human Resources", leave_balances=EmployeeBalances(
        vacation=LeaveBalance(allocated=20, used=5),
        sick=LeaveBalance(allocated=10, used=1)
    )),
]

leave_db: List[LeaveRequest] = [
    LeaveRequest(id=1, employee_id=2, leave_type=LeaveType.VACATION, start_date="2025-10-20", end_date="2025-10-22", reason="Family vacation.", status=LeaveStatus.APPROVED),
]

# --- FastAPI Application Instance ---
app = FastAPI(
    title="HR Management API",
    description="An API to manage employees, their leave requests, and quotas.",
    version="1.2.0",
)


# --- Helper Functions ---

def find_employee(employee_id: int) -> Employee:
    """Finds an employee by ID or raises HTTPException."""
    for employee in employee_db:
        if employee.id == employee_id:
            return employee
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Employee with ID {employee_id} not found")

def calculate_business_days(start_date: date, end_date: date) -> int:
    """Calculates the number of business days (Mon-Fri) between two dates, inclusive."""
    if start_date > end_date:
        return 0
    days = (end_date - start_date).days + 1
    # Count the number of weekends
    weekend_days = sum(1 for i in range(days) if (start_date + timedelta(days=i)).weekday() >= 5)
    return days - weekend_days


# --- Root Endpoint ---

@app.get("/")
def read_root():
    """A simple root endpoint to confirm the API is running."""
    return {"message": "Welcome to the HR API!"}

# --- Employee Endpoints ---

@app.get("/employees", response_model=List[Employee])
def get_all_employees():
    return employee_db

@app.get("/employees/{employee_id}", response_model=Employee)
def get_employee_by_id(employee_id: int):
    return find_employee(employee_id)

@app.post("/employees", response_model=Employee, status_code=status.HTTP_201_CREATED)
def create_employee(employee_data: CreateEmployee):
    new_id = max(emp.id for emp in employee_db) + 1 if employee_db else 1
    # New employees get default leave balances
    new_employee = Employee(id=new_id, **employee_data.dict(), leave_balances=EmployeeBalances())
    employee_db.append(new_employee)
    return new_employee

@app.put("/employees/{employee_id}", response_model=Employee)
def update_employee(employee_id: int, updated_data: CreateEmployee):
    employee = find_employee(employee_id)
    # Preserve existing leave balances when updating other details
    employee.name = updated_data.name
    employee.position = updated_data.position
    employee.department = updated_data.department
    return employee

@app.delete("/employees/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_employee(employee_id: int):
    employee_to_delete = find_employee(employee_id)
    employee_db.remove(employee_to_delete)
    return

# --- Quota and Leave Endpoints ---

@app.get("/employees/{employee_id}/leave-balance", response_model=EmployeeBalances)
def get_employee_leave_balance(employee_id: int):
    """Retrieve the current leave balances for a specific employee."""
    employee = find_employee(employee_id)
    return employee.leave_balances

@app.post("/employees/{employee_id}/leave", response_model=LeaveRequest, status_code=status.HTTP_201_CREATED)
def create_leave_request(employee_id: int, request_data: CreateLeaveRequest):
    employee = find_employee(employee_id)
    
    leave_duration = calculate_business_days(request_data.start_date, request_data.end_date)
    if leave_duration <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="End date must be after start date.")

    balance = getattr(employee.leave_balances, request_data.leave_type.value)
    if balance.remaining < leave_duration:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, 
                            detail=f"Insufficient {request_data.leave_type.value} leave balance. "
                                   f"Required: {leave_duration}, Available: {balance.remaining}")

    new_id = max(req.id for req in leave_db) + 1 if leave_db else 1
    new_request = LeaveRequest(id=new_id, employee_id=employee_id, **request_data.dict())
    leave_db.append(new_request)
    return new_request

@app.get("/leave", response_model=List[LeaveRequest])
def get_all_leave_requests(status: Optional[LeaveStatus] = None):
    if status:
        return [req for req in leave_db if req.status == status]
    return leave_db

@app.get("/employees/{employee_id}/leave", response_model=List[LeaveRequest])
def get_employee_leave_requests(employee_id: int):
    find_employee(employee_id)
    return [req for req in leave_db if req.employee_id == employee_id]

@app.patch("/leave/{request_id}", response_model=LeaveRequest)
def update_leave_request_status(request_id: int, status_update: UpdateLeaveStatus):
    """Update the status of a leave request and adjusts employee's leave balance if approved."""
    request_to_update = None
    for req in leave_db:
        if req.id == request_id:
            request_to_update = req
            break
    
    if not request_to_update:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Leave request with ID {request_id} not found")

    employee = find_employee(request_to_update.employee_id)
    leave_duration = calculate_business_days(request_to_update.start_date, request_to_update.end_date)
    balance = getattr(employee.leave_balances, request_to_update.leave_type.value)

    # Logic to adjust balances based on status change
    is_newly_approved = status_update.status == LeaveStatus.APPROVED and request_to_update.status != LeaveStatus.APPROVED
    was_previously_approved = request_to_update.status == LeaveStatus.APPROVED and status_update.status != LeaveStatus.APPROVED

    if is_newly_approved:
        if balance.remaining < leave_duration:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Cannot approve. Employee has insufficient {request_to_update.leave_type.value} balance.")
        balance.used += leave_duration
    elif was_previously_approved:
        # Reclaim the days if an approved request is rejected or set back to pending
        balance.used -= leave_duration

    request_to_update.status = status_update.status
    return request_to_update