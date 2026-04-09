FROM public.ecr.aws/lambda/python:3.12

# Install Z3 solver
RUN pip install z3-solver==4.13.4.0 --target "${LAMBDA_TASK_ROOT}"

# Copy handler code
COPY handler.py ${LAMBDA_TASK_ROOT}/

# AWS Lambda base image manages runtime user internally.
CMD ["handler.lambda_handler"]
