MINIKUBE_PROFILE ?= minikube
IMAGE ?= service-registry:latest

.PHONY: up build deploy wait client logs clean status

up: build deploy wait

status:
	minikube -p $(MINIKUBE_PROFILE) status
	kubectl get pods,svc

build:
	minikube -p $(MINIKUBE_PROFILE) start
	# Build the image into the Minikube Docker daemon.
	eval $$(minikube -p $(MINIKUBE_PROFILE) docker-env) && docker build -t $(IMAGE) .

deploy:
	kubectl apply -f k8s/registry-deployment.yaml
	kubectl apply -f k8s/services-deployment.yaml

wait:
	kubectl rollout status deployment/service-registry --timeout=180s
	kubectl rollout status deployment/user-service --timeout=240s
	kubectl rollout status deployment/payment-service --timeout=240s

client:
	kubectl delete job discovery-client --ignore-not-found
	kubectl apply -f k8s/discovery-client-job.yaml

logs:
	kubectl logs -l app=discovery-client --tail=200 --all-containers=true

clean:
	kubectl delete -f k8s/discovery-client-job.yaml --ignore-not-found
	kubectl delete -f k8s/services-deployment.yaml --ignore-not-found
	kubectl delete -f k8s/registry-deployment.yaml --ignore-not-found

